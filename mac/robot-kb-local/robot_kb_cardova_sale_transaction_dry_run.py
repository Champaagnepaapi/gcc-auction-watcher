#!/usr/bin/env python3
"""Validate Cardova paid/completed auctions against the pinned Robot KB P3 sale contract.

This module is deliberately memory-only. It consumes the already-sanitized output
from ``robot_kb_cardova_paid_sold_harvest.py`` and constructs P3
``SALE_TRANSACTION`` observations without opening the user's PostgreSQL database.

Semantics:
- Cardova must already prove PAID_COMPLETED status, JPY and a positive final bid;
- ``auction_end_at_utc`` is the sale event time (auction close), not a fabricated
  payment-completion timestamp;
- the final winning bid is stored as ``HAMMER_PRICE`` in JPY;
- canonical identity and commercial microvariant remain unresolved;
- no exact canonical link is created;
- no production database, V4 economics, notification or commerce action is used.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402

from robot_kb.domain import InclusionState, ObservationType, SourceKind  # noqa: E402
from robot_kb.repository import KnowledgeBase, PriceComponent  # noqa: E402
from robot_kb.sidecar.models import (  # noqa: E402
    IdentityClaim,
    NormalizedObservation,
    RawSourceRecord,
    ShadowDiagnostics,
)
from robot_kb.sidecar.persistence import ShadowKnowledgePersistence  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
SOURCE_CODE = "cardova"
SOURCE_NAME = "Cardova"
SOURCE_ROLE = "LISTING_PLATFORM"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _positive_int(value: object) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _aware_utc(value: object) -> Optional[str]:
    raw = _norm(value)
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _claim_rows(record: Mapping[str, Any]) -> tuple[IdentityClaim, ...]:
    rows = (
        ("card_name", record.get("card_name")),
        ("set", record.get("set_name")),
        ("collector_number", record.get("collector_number")),
        ("language", record.get("language")),
        ("grader", record.get("grader")),
        ("grade", record.get("grade")),
        ("certification_number", record.get("certification_number")),
        ("provider_set_name_short", record.get("provider_set_name_short")),
        ("provider_series", record.get("provider_series")),
        ("provider_title", record.get("provider_title")),
        ("provider_item_name", record.get("provider_item_name")),
        ("provider_sale_status", record.get("provider_sale_status")),
    )
    return tuple(
        IdentityClaim(key, _norm(value), SourceKind.PROVIDER)
        for key, value in rows
        if _norm(value)
    )


def build_p3_sale(
    record: Mapping[str, Any],
    *,
    observed_at: str,
) -> tuple[Optional[tuple[RawSourceRecord, NormalizedObservation]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason

    event_at = _aware_utc(record.get("auction_end_at_utc"))
    if event_at is None:
        return None, "AUCTION_END_INVALID"
    observed = _aware_utc(observed_at)
    if observed is None:
        return None, "OBSERVED_AT_INVALID"
    if event_at > observed:
        return None, "SALE_EVENT_AFTER_OBSERVATION"

    hammer_jpy = _positive_int(record.get("final_bid_jpy"))
    if hammer_jpy is None:
        return None, "FINAL_BID_INVALID"
    if _norm(record.get("currency")).upper() != "JPY" or record.get("currency_proven") is not True:
        return None, "CURRENCY_NOT_PROVEN_JPY"

    native_id = _norm(record.get("source_native_record_id"))
    if not native_id:
        return None, "SOURCE_ID_MISSING"

    raw = RawSourceRecord(
        source_code=SOURCE_CODE,
        source_name=SOURCE_NAME,
        source_role=SOURCE_ROLE,
        source_native_record_id=native_id,
        payload=dict(record),
        retrieved_at=observed,
        object_type="LISTING",
        external_native_id=native_id,
    )
    observation = NormalizedObservation(
        observation_type=ObservationType.SALE_TRANSACTION,
        source_native_record_id=native_id,
        observed_at=observed,
        event_at=event_at,
        event_time_precision="EXACT",
        fact={
            "listing_started_at": None,
            "sale_occurred_at": event_at,
            "transaction_status": "COMPLETED",
        },
        prices=(
            PriceComponent(
                "HAMMER_PRICE",
                hammer_jpy,
                "JPY",
                inclusion_state=InclusionState.UNKNOWN,
            ),
        ),
        identity_subject_type="CARDOVA_PAID_AUCTION_SALE",
        identity_subject_label=f"Cardova paid auction {native_id}",
        identity_namespace="CARDOVA_AUCTION_ULID",
        identity_identifier_value=native_id,
        unresolved_dimensions=("canonical_identity", "commercial_microvariant"),
        claims=_claim_rows(record),
        exact_identity_eligible=False,
        genuine_sale_evidence=True,
    )
    return (raw, observation), "P3_SALE_READY_UNRESOLVED_IDENTITY"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "MEMORY_ONLY_CARDOVA_PAID_SOLD_P3_SALE_TRANSACTION_DRY_RUN",
        "database": ":memory:",
        "durable_robot_kb_write": False,
        "sale_event_semantics": "AUCTION_END_AT_UTC",
        "payment_completion_timestamp_fabricated": False,
        "price_component": "HAMMER_PRICE",
        "currency": "JPY",
        "canonical_identity_required_for_storage": False,
        "canonical_identity_claimed": False,
        "commercial_microvariant_claimed": False,
        "exact_identity_eligible": False,
        "genuine_sale_evidence": True,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_memory_dry_run(
    records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    observed_at: Optional[str] = None,
    replay: bool = True,
) -> Mapping[str, Any]:
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    selected = list(records[:max_records])
    prepared: list[tuple[RawSourceRecord, NormalizedObservation]] = []
    blocked: Counter[str] = Counter()
    for record in selected:
        built, reason = build_p3_sale(record, observed_at=observed)
        if built is None:
            blocked[reason] += 1
            continue
        prepared.append(built)

    first = ShadowDiagnostics()
    replay_diag = ShadowDiagnostics()
    with KnowledgeBase.open(":memory:") as kb:
        persistence = ShadowKnowledgePersistence(kb)
        for raw, observation in prepared:
            persistence.ingest(raw, (observation,), first)
        stored_sales = kb.connection.execute(
            "SELECT COUNT(*) AS n FROM market_observation WHERE observation_type = 'SALE_TRANSACTION'"
        ).fetchone()["n"]
        canonical_links = kb.connection.execute(
            "SELECT COUNT(*) AS n FROM market_observation WHERE observation_type = 'SALE_TRANSACTION' AND canonical_card_id IS NOT NULL"
        ).fetchone()["n"]
        unresolved_sales = kb.connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM market_observation AS observation
            JOIN observation_identity_link AS link ON link.observation_id = observation.id
            JOIN identity_resolution AS resolution ON resolution.id = link.identity_resolution_id
            WHERE observation.observation_type = 'SALE_TRANSACTION'
              AND resolution.resolution_state = 'UNKNOWN'
            """
        ).fetchone()["n"]
        hammer_rows = kb.connection.execute(
            """
            SELECT COUNT(*) AS n FROM price_component AS price
            JOIN market_observation AS observation ON observation.id = price.observation_id
            WHERE observation.observation_type = 'SALE_TRANSACTION'
              AND price.component_type = 'HAMMER_PRICE'
              AND price.currency = 'JPY'
            """
        ).fetchone()["n"]
        if replay:
            for raw, observation in prepared:
                persistence.ingest(raw, (observation,), replay_diag)
        stored_sales_after_replay = kb.connection.execute(
            "SELECT COUNT(*) AS n FROM market_observation WHERE observation_type = 'SALE_TRANSACTION'"
        ).fetchone()["n"]

    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "prepared_sale_transactions": len(prepared),
        "blocked": dict(sorted(blocked.items())),
        "sale_transactions_stored_in_memory": int(stored_sales),
        "unresolved_identity_sales": int(unresolved_sales),
        "canonical_card_links": int(canonical_links),
        "hammer_price_jpy_rows": int(hammer_rows),
        "replay_executed": bool(replay),
        "sale_transactions_after_replay": int(stored_sales_after_replay),
        "duplicate_sale_replays": int(replay_diag.duplicate_sale_replays),
        "first_pass_diagnostics": dict(first.as_dict()),
        "replay_diagnostics": dict(replay_diag.as_dict()),
    }


def load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON must be an object")
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(row, Mapping) for row in records):
        raise ValueError("input JSON must contain object records[]")
    return list(records)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Memory-only P3 dry-run for Cardova paid SOLD transactions")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    summary = safe_summary()
    try:
        records = load_records(args.input)
        summary.update(run_memory_dry_run(records, max_records=args.max_records))
        code = 0
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        code = 1
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
