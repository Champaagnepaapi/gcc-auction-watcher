"""Read-only Robot KB ROI analytics.

This script reads the durable Neon ledger and emits aggregate/shadow analytics.
It does not write to Neon, does not feed V4 economics, and never turns asks or
live auctions into sales.

Current purpose:
* measure when Robot KB is actually deep enough for a future KB-first policy;
* quantify exact-identity depth for cache/coverage decisions;
* learn conservative same-grade PSA/secondary-grader SOLD ratios only when the
  stored GCC claims are complete enough to create a strict deterministic key.

Until those readiness thresholds are met per identity, V4 must continue using
its external providers normally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable, Optional


FOCUS_CLAIMS = (
    "card_title_raw",
    "set",
    "collector_number",
    "language",
    "edition",
    "grader",
    "grade",
)
GRADER_PREFIX_RE = re.compile(
    r"^\s*(?:PSA|PCA|CCC|CGC|BGS|BECKETT|SGC|SGS|SFG|CA|ACE|GRAAD|AP|GEM|PG|SCA|TCC)"
    r"\s*(?:GRADE\s*)?(?:10|[1-9](?:[.,]5)?)\+?\s*",
    re.I,
)


@dataclass(frozen=True)
class SaleRow:
    occurred_at: datetime
    amount_minor: int
    currency: str
    card_key: str
    identity_hash: str
    grader: str
    grade: float


@dataclass(frozen=True)
class GraderSpread:
    identity_hash: str
    grade: float
    source_grader: str
    target_grader: str
    source_n: int
    target_n: int
    source_median: float
    target_median: float
    target_per_source_ratio: float
    first_sale_at: str
    last_sale_at: str


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _claim_value(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw)
    try:
        decoded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        decoded = text
    if decoded is None:
        return ""
    return str(decoded).strip()


def _parse_time(value: object) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_grade(value: object) -> Optional[float]:
    try:
        grade = float(str(value or "").replace(",", "."))
    except ValueError:
        return None
    return grade if 0 < grade <= 10 else None


def strict_card_key(claims: dict[str, object]) -> str:
    """Build a conservative deterministic card key from explicit GCC claims.

    No missing field receives a default. The title remains part of the key after
    only stripping an explicit grader/grade prefix, which keeps visible Holo /
    promo wording separated instead of merging it away.
    """
    title = _claim_value(claims.get("card_title_raw"))
    title_core = GRADER_PREFIX_RE.sub("", title).strip()
    parts = {
        "title": _normalise(title_core),
        "set": _normalise(_claim_value(claims.get("set"))),
        "number": _normalise(_claim_value(claims.get("collector_number"))),
        "language": _normalise(_claim_value(claims.get("language"))),
        "edition": _normalise(_claim_value(claims.get("edition"))),
    }
    if any(not value for value in parts.values()):
        return ""
    return json.dumps(
        parts, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def identity_hash(card_key: str) -> str:
    return hashlib.sha256(card_key.encode("utf-8")).hexdigest()


def _fetch_gcc_sales(connection) -> list[SaleRow]:
    claim_selects = ",\n".join(
        f"MAX(fc.claimed_value_json) FILTER (WHERE fc.field_name = '{name}') AS {name}"
        for name in FOCUS_CLAIMS
    )
    sql = f"""
        SELECT
            st.sale_occurred_at,
            pc.amount_minor,
            pc.currency,
            {claim_selects}
        FROM sale_transaction st
        JOIN market_observation mo ON mo.id = st.observation_id
        JOIN source_system ss ON ss.id = mo.source_system_id
        JOIN price_component pc
          ON pc.observation_id = mo.id
         AND pc.component_type = 'ITEM_PRICE'
        LEFT JOIN field_claim fc ON fc.source_record_id = mo.source_record_id
        WHERE ss.name = 'GCC Marketplace'
          AND st.transaction_status = 'COMPLETED'
        GROUP BY st.observation_id, st.sale_occurred_at, pc.amount_minor, pc.currency
        ORDER BY st.sale_occurred_at ASC
    """
    rows: list[SaleRow] = []
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [description.name for description in cursor.description]
        for raw_row in cursor.fetchall():
            record = dict(zip(columns, raw_row))
            occurred_at = _parse_time(record.get("sale_occurred_at"))
            if occurred_at is None:
                continue
            try:
                amount_minor = int(record.get("amount_minor"))
            except (TypeError, ValueError):
                continue
            currency = str(record.get("currency") or "").upper()
            if amount_minor <= 0 or not currency:
                continue
            claims = {name: record.get(name) for name in FOCUS_CLAIMS}
            card_key = strict_card_key(claims)
            grader = _normalise(_claim_value(claims.get("grader"))).upper()
            grade = _parse_grade(_claim_value(claims.get("grade")))
            if not card_key or not grader or grade is None:
                continue
            rows.append(
                SaleRow(
                    occurred_at=occurred_at,
                    amount_minor=amount_minor,
                    currency=currency,
                    card_key=card_key,
                    identity_hash=identity_hash(card_key),
                    grader=grader,
                    grade=grade,
                )
            )
    return rows


def _depth_summary(rows: Iterable[SaleRow], now: datetime) -> dict:
    tiers: dict[tuple[str, str, float], list[SaleRow]] = defaultdict(list)
    for row in rows:
        tiers[(row.identity_hash, row.grader, row.grade)].append(row)
    recent_cutoff = now - timedelta(days=90)
    ready = 0
    for sales in tiers.values():
        recent = sum(row.occurred_at >= recent_cutoff for row in sales)
        if len(sales) >= 3 and recent >= 2:
            ready += 1
    counts = [len(sales) for sales in tiers.values()]
    return {
        "distinct_exact_slab_tiers": len(tiers),
        "tiers_with_2plus_sales": sum(count >= 2 for count in counts),
        "tiers_with_3plus_sales": sum(count >= 3 for count in counts),
        "tiers_with_5plus_sales": sum(count >= 5 for count in counts),
        "kb_first_ready_tiers": ready,
        "kb_first_ready_rule": (
            "same strict card + grader + grade: >=3 proven GCC SOLD, >=2 within 90d"
        ),
    }


def learn_grader_spreads(
    rows: Iterable[SaleRow],
    *,
    min_sales_per_side: int = 2,
    max_window_days: int = 365,
) -> list[GraderSpread]:
    groups: dict[tuple[str, float, str], list[SaleRow]] = defaultdict(list)
    for row in rows:
        if row.currency != "EUR":
            # No FX synthesis in this shadow learner.
            continue
        groups[(row.identity_hash, row.grade, row.grader)].append(row)

    identities = sorted({(identity, grade) for identity, grade, _grader in groups})
    result: list[GraderSpread] = []
    for identity, grade in identities:
        psa = groups.get((identity, grade, "PSA"), [])
        if len(psa) < min_sales_per_side:
            continue
        for (candidate_identity, candidate_grade, grader), target_sales in groups.items():
            if candidate_identity != identity or candidate_grade != grade or grader == "PSA":
                continue
            if len(target_sales) < min_sales_per_side:
                continue
            combined_dates = [row.occurred_at for row in psa + target_sales]
            first_at = min(combined_dates)
            last_at = max(combined_dates)
            if (last_at - first_at).days > max_window_days:
                continue
            psa_prices = [row.amount_minor / 100 for row in psa]
            target_prices = [row.amount_minor / 100 for row in target_sales]
            psa_median = median(psa_prices)
            target_median = median(target_prices)
            if psa_median <= 0 or target_median <= 0:
                continue
            result.append(
                GraderSpread(
                    identity_hash=identity,
                    grade=grade,
                    source_grader="PSA",
                    target_grader=grader,
                    source_n=len(psa),
                    target_n=len(target_sales),
                    source_median=round(psa_median, 2),
                    target_median=round(target_median, 2),
                    target_per_source_ratio=round(target_median / psa_median, 4),
                    first_sale_at=first_at.isoformat(),
                    last_sale_at=last_at.isoformat(),
                )
            )
    result.sort(
        key=lambda spread: (
            -(spread.source_n + spread.target_n),
            spread.identity_hash,
            spread.grade,
            spread.target_grader,
        )
    )
    return result


def build_snapshot(connection, now: Optional[datetime] = None) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    rows = _fetch_gcc_sales(connection)
    depth = _depth_summary(rows, current)
    spreads = learn_grader_spreads(rows)
    latest = max((row.occurred_at for row in rows), default=None)
    oldest = min((row.occurred_at for row in rows), default=None)
    global_ready = depth["kb_first_ready_tiers"] >= 100
    return {
        "schema_version": 1,
        "generated_at": current.astimezone(timezone.utc).isoformat(),
        "mode": "SHADOW_ONLY_READ_ONLY",
        "v4_economic_use": False,
        "expected_profit_score_enabled": False,
        "gcc_proven_sales_with_strict_identity": len(rows),
        "oldest_gcc_sale": oldest.isoformat() if oldest else None,
        "latest_gcc_sale": latest.isoformat() if latest else None,
        "identity_depth": depth,
        "kb_first_global_readiness": {
            "ready": global_ready,
            "policy": (
                "NO HARD GATE: use KB first only after enough exact tiers are individually ready"
            ),
            "activation_floor_ready_tiers": 100,
        },
        "learned_grader_spreads_count": len(spreads),
        "learned_grader_spreads": [spread.__dict__ for spread in spreads[:200]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="robot_kb_roi_snapshot.json")
    args = parser.parse_args()
    database_url = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("ROBOT_KB_DATABASE_URL is required")

    # psycopg is intentionally runtime-only: V4 CI can unit-test all pure
    # analytics without installing the Robot KB PostgreSQL dependency.
    import psycopg

    with psycopg.connect(database_url) as connection:
        # Explicit read-only transaction: this analytics job cannot mutate Neon.
        connection.execute("SET TRANSACTION READ ONLY")
        snapshot = build_snapshot(connection)
    Path(args.output).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    depth = snapshot["identity_depth"]
    print(
        "Robot KB ROI analytics: "
        f"strict_sales={snapshot['gcc_proven_sales_with_strict_identity']} | "
        f"exact_tiers={depth['distinct_exact_slab_tiers']} | "
        f"kb_first_ready={depth['kb_first_ready_tiers']} | "
        f"grader_spreads={snapshot['learned_grader_spreads_count']} | "
        "V4_USE=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
