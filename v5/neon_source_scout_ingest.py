from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import psycopg


EVIDENCE_PATH = Path("pokemonpricetracker_evidence.json")
SOURCE_CODES = {
    "pokemonpricetracker": ("PokemonPriceTracker", "PROVIDER"),
    "tcgplayer": ("TCGplayer", "MARKET"),
    "cardmarket": ("Cardmarket", "MARKET"),
    "ebay": ("eBay", "MARKET"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{_digest('|'.join(str(part) for part in parts))[:32]}"


def _num(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _minor(value: object) -> int | None:
    number = _num(value)
    return None if number is None else int(round(number * 100))


def _first_row(payload: object) -> Mapping[str, object] | None:
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if isinstance(data, Mapping):
        return data
    if isinstance(data, list):
        for row in data:
            if isinstance(row, Mapping):
                return row
    return None


def _source_updated_at(row: Mapping[str, object]) -> str | None:
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    for value in (row.get("updatedAt"), row.get("lastScrapedAt"), prices.get("lastUpdated")):
        if value not in (None, ""):
            return str(value)
    return None


def _role_suffix(evidence: Mapping[str, object]) -> str:
    return "ANCHOR_EN_FOR_FR" if evidence.get("identity_status") == "ANCHOR_ONLY" else "EXACT_CARD"


def _ensure_source(cur: psycopg.Cursor[Any], code: str, name: str, role: str) -> str:
    source_id = _id("source", code)
    cur.execute(
        """
        INSERT INTO source_system (id, code, name, system_role, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (code) DO NOTHING
        """,
        (source_id, code, name, role, _now()),
    )
    cur.execute("SELECT id FROM source_system WHERE code = %s", (code,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"source_system missing after upsert: {code}")
    return str(row[0])


def _insert_metric(
    cur: psycopg.Cursor[Any],
    *,
    provider_source_id: str,
    upstream_source_id: str | None,
    source_record_id: str,
    source_native_record_id: str,
    payload_sha256: str,
    metric_name: str,
    observed_at: str,
    source_updated_at: str | None,
    amount_minor: int | None = None,
    currency: str | None = None,
    sample_size: int | None = None,
    event_at: str | None = None,
    window_started_at: str | None = None,
    window_ended_at: str | None = None,
) -> bool:
    if amount_minor is None:
        currency = None
    metric_content = {
        "source_record_id": source_record_id,
        "source_native_record_id": source_native_record_id,
        "metric_name": metric_name,
        "amount_minor": amount_minor,
        "currency": currency,
        "sample_size": sample_size,
        "event_at": event_at,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "payload_sha256": payload_sha256,
    }
    content_sha = _digest(metric_content)
    idempotency_key = f"obskey_{_digest(['pokemonpricetracker', source_native_record_id, payload_sha256])}"
    observation_id = _id("observation", idempotency_key)
    created_at = _now()
    event_value = event_at or source_updated_at or observed_at

    cur.execute(
        """
        INSERT INTO market_observation (
            id, observation_type, source_system_id, upstream_market_system_id,
            source_record_id, source_native_record_id, upstream_event_object_id,
            canonical_card_id, idempotency_key, content_sha256, event_at,
            event_time_precision, observed_at, ingested_at, source_updated_at,
            revision_of_observation_id, created_at, lifecycle_state, sealed_at
        ) VALUES (
            %s, 'PROVIDER_METRIC_OBSERVATION', %s, %s,
            %s, %s, NULL,
            NULL, %s, %s, %s,
            'EXACT', %s, %s, %s,
            NULL, %s, 'SEALED', %s
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            observation_id,
            provider_source_id,
            upstream_source_id,
            source_record_id,
            source_native_record_id,
            idempotency_key,
            content_sha,
            event_value,
            observed_at,
            created_at,
            source_updated_at,
            created_at,
            created_at,
        ),
    )
    inserted = cur.rowcount > 0
    cur.execute("SELECT id FROM market_observation WHERE idempotency_key = %s", (idempotency_key,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"market_observation missing after upsert: {source_native_record_id}")
    observation_id = str(row[0])
    cur.execute(
        """
        INSERT INTO provider_metric_observation (
            observation_id, metric_name, metric_value_minor, currency,
            window_started_at, window_ended_at, sample_size
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (
            observation_id,
            metric_name,
            amount_minor,
            currency,
            window_started_at,
            window_ended_at,
            sample_size,
        ),
    )
    return inserted


def _price_metric_specs(row: Mapping[str, object], role: str) -> list[tuple[str, str, int | None, str | None, int | None]]:
    specs: list[tuple[str, str, int | None, str | None, int | None]] = []
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    for field, label in (
        ("market", "MARKET"),
        ("low", "LOW"),
        ("mid", "MID"),
        ("high", "HIGH"),
        ("directLow", "DIRECT_LOW"),
    ):
        amount = _minor(prices.get(field))
        if amount is not None:
            specs.append(("tcgplayer", f"PPT_TCGPLAYER_{label}:{role}", amount, "USD", None))

    cardmarket = row.get("cardmarketPrices")
    if isinstance(cardmarket, Mapping):
        for field, label in (
            ("marketEur", "MARKET"),
            ("trendEur", "TREND"),
            ("lowEur", "LOW"),
        ):
            amount = _minor(cardmarket.get(field))
            if amount is not None:
                specs.append(("cardmarket", f"PPT_CARDMARKET_{label}:{role}", amount, "EUR", None))

    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    total_sales = _integer(ebay.get("totalSales"))
    if total_sales is not None:
        specs.append(("ebay", f"PPT_EBAY_TOTAL_SALES:ALL_GRADES:{role}", None, None, total_sales))

    sales_by_grade = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    for grade_key, grade_row in sales_by_grade.items():
        grade_token = str(grade_key).upper().replace(" ", "_").replace("-", "_")
        if isinstance(grade_row, Mapping):
            amount = None
            for key in ("averagePrice", "average", "avg", "median", "price"):
                amount = _minor(grade_row.get(key))
                if amount is not None:
                    break
            grade_sales = None
            for key in ("totalSales", "sales", "count", "saleCount", "sampleSize"):
                grade_sales = _integer(grade_row.get(key))
                if grade_sales is not None:
                    break
            if amount is not None:
                specs.append(("ebay", f"PPT_EBAY_{grade_token}_AGGREGATE_PRICE:{role}", amount, "USD", grade_sales))
            elif grade_sales is not None:
                specs.append(("ebay", f"PPT_EBAY_{grade_token}_SALES_COUNT:{role}", None, None, grade_sales))
        else:
            amount = _minor(grade_row)
            if amount is not None:
                specs.append(("ebay", f"PPT_EBAY_{grade_token}_AGGREGATE_PRICE:{role}", amount, "USD", None))

    history = row.get("priceHistory")
    if isinstance(history, list):
        specs.append(("tcgplayer", f"PPT_PRICE_HISTORY_POINTS:180D:{role}", None, None, len(history)))
    elif isinstance(history, Mapping):
        specs.append(("tcgplayer", f"PPT_PRICE_HISTORY_SERIES:180D:{role}", None, None, len(history)))
    return specs


def ingest(connection_string: str, evidence_path: Path = EVIDENCE_PATH) -> dict[str, int]:
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_rows = document.get("evidence") if isinstance(document, Mapping) else None
    if not isinstance(evidence_rows, list):
        raise RuntimeError("PokemonPriceTracker evidence sidecar is malformed")

    stats = {"evidence": 0, "payloads": 0, "source_records": 0, "metrics": 0}
    with psycopg.connect(connection_string) as conn:
        with conn.cursor() as cur:
            source_ids = {
                code: _ensure_source(cur, code, name, role)
                for code, (name, role) in SOURCE_CODES.items()
            }

            for evidence in evidence_rows:
                if not isinstance(evidence, Mapping):
                    continue
                payload = evidence.get("provider_payload")
                row = _first_row(payload)
                tcg_id = str(evidence.get("provider_tcgplayer_id") or "").strip()
                tcgdex_id = str(evidence.get("tcgdex_id") or "").strip()
                if row is None or not tcg_id or not tcgdex_id:
                    continue

                payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                payload_bytes = payload_json.encode("utf-8")
                payload_sha = _digest(payload_bytes)
                retrieved_at = str(evidence.get("retrieved_at") or _now())
                source_updated_at = _source_updated_at(row)
                role = _role_suffix(evidence)
                source_native = f"ppt:tcgplayer:{tcg_id}:tcgdex:{tcgdex_id}:{role}"
                source_record_id = _id("srecord", source_native, payload_sha)
                created_at = _now()

                cur.execute(
                    """
                    INSERT INTO source_payload (
                        payload_sha256, payload_bytes, payload_format, byte_length, created_at
                    ) VALUES (%s, %s, 'CANONICAL_JSON', %s, %s)
                    ON CONFLICT (payload_sha256) DO NOTHING
                    """,
                    (payload_sha, payload_bytes, len(payload_bytes), created_at),
                )
                stats["payloads"] += max(cur.rowcount, 0)

                cur.execute(
                    """
                    INSERT INTO source_record (
                        id, source_system_id, external_object_id, source_native_record_id,
                        payload_sha256, retrieved_at, source_updated_at, created_at
                    ) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_system_id, source_native_record_id, payload_sha256) DO NOTHING
                    """,
                    (
                        source_record_id,
                        source_ids["pokemonpricetracker"],
                        source_native,
                        payload_sha,
                        retrieved_at,
                        source_updated_at,
                        created_at,
                    ),
                )
                stats["source_records"] += max(cur.rowcount, 0)

                cur.execute(
                    """
                    INSERT INTO source_record_payload (source_record_id, payload_sha256, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_record_id) DO NOTHING
                    """,
                    (source_record_id, payload_sha, created_at),
                )

                lineage_key = f"lineage_{_digest([source_record_id, retrieved_at])}"
                retrieval_id = _id("sretrieval", lineage_key)
                cur.execute(
                    """
                    INSERT INTO source_record_retrieval (
                        id, source_record_id, external_object_id, retrieved_at,
                        source_updated_at, lineage_key, created_at
                    ) VALUES (%s, %s, NULL, %s, %s, %s, %s)
                    ON CONFLICT (lineage_key) DO NOTHING
                    """,
                    (
                        retrieval_id,
                        source_record_id,
                        retrieved_at,
                        source_updated_at,
                        lineage_key,
                        created_at,
                    ),
                )

                for upstream_code, metric_name, amount_minor, currency, sample_size in _price_metric_specs(row, role):
                    metric_native = f"{source_native}:{metric_name}"
                    if _insert_metric(
                        cur,
                        provider_source_id=source_ids["pokemonpricetracker"],
                        upstream_source_id=source_ids[upstream_code],
                        source_record_id=source_record_id,
                        source_native_record_id=metric_native,
                        payload_sha256=payload_sha,
                        metric_name=metric_name,
                        observed_at=retrieved_at,
                        source_updated_at=source_updated_at,
                        amount_minor=amount_minor,
                        currency=currency,
                        sample_size=sample_size,
                    ):
                        stats["metrics"] += 1
                stats["evidence"] += 1
        conn.commit()
    return stats


def main() -> int:
    connection_string = os.getenv("NEON_DATABASE_URL", "").strip()
    if not connection_string:
        print("NEON_INGEST skipped: NEON_DATABASE_URL not configured")
        return 0
    if not EVIDENCE_PATH.exists():
        print("NEON_INGEST skipped: evidence sidecar not found")
        return 0
    stats = ingest(connection_string)
    print(
        "NEON_INGEST "
        + " ".join(f"{key}={value}" for key, value in stats.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
