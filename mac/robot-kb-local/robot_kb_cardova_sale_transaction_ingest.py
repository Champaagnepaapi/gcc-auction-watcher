#!/usr/bin/env python3
"""Guarded local PostgreSQL ingest for proven Cardova paid/completed SOLD rows.

This is a deliberately manual one-shot bridge from the already-sanitized Cardova
paid-SOLD harvest into the pinned Robot KB P3 ledger.

Safety contract:
- explicit ``--commit`` is required;
- only a local PostgreSQL target named ``robot_pokemon_kb`` is accepted;
- remote/Neon/cloud database URLs are rejected before opening a connection;
- every selected row must pass the already-proven P3 Cardova sale builder;
- an existing immutable ``source_system.code='cardova'`` is reused exactly as-is;
  this writer never renames or changes the role of that provenance row;
- the whole batch runs inside one outer P3 transaction; postconditions are checked
  before commit, so any contradiction rolls the entire batch back;
- canonical identity and commercial microvariant remain unresolved;
- the final winning bid is stored only as ``HAMMER_PRICE`` in JPY;
- no V4 economic use, notification or commerce action is performed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_sale_transaction_dry_run as dry_run  # noqa: E402

from robot_kb.repository import KnowledgeBase  # noqa: E402
from robot_kb.sidecar.models import ShadowDiagnostics  # noqa: E402
from robot_kb.sidecar.persistence import ShadowKnowledgePersistence  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
EXPECTED_DATABASE_NAME = "robot_pokemon_kb"
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_local_database_url(database_url: str) -> dict[str, Any]:
    """Fail closed unless the target is the canonical local Mac PostgreSQL DB."""

    raw = str(database_url or "").strip()
    if not raw:
        raise ValueError("ROBOT_KB_DATABASE_URL is required")
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"postgres", "postgresql"}:
        raise ValueError("only PostgreSQL is allowed for durable Cardova ingest")
    host = (parsed.hostname or "").casefold()
    if host not in LOCAL_DATABASE_HOSTS:
        raise ValueError("remote/cloud Robot KB writes are forbidden for this ingest")
    database_name = parsed.path.lstrip("/").split("/", 1)[0]
    if database_name != EXPECTED_DATABASE_NAME:
        raise ValueError(
            f"database must be exactly {EXPECTED_DATABASE_NAME!r} for this ingest"
        )
    return {
        "database_scope": "LOCAL_MAC_POSTGRES_ONLY",
        "database_host_class": "LOOPBACK",
        "database_name": EXPECTED_DATABASE_NAME,
        "database_port": parsed.port,
    }


def _prepared_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    observed_at: str,
) -> tuple[list[tuple[Any, Any]], dict[str, int], int]:
    selected = list(records[:max_records])
    prepared: list[tuple[Any, Any]] = []
    blocked: Counter[str] = Counter()
    for record in selected:
        built, reason = dry_run.build_p3_sale(record, observed_at=observed_at)
        if built is None:
            blocked[reason] += 1
            continue
        prepared.append(built)
    return prepared, dict(sorted(blocked.items())), len(selected)


def _reuse_existing_cardova_source_metadata(
    kb: KnowledgeBase,
    prepared: Sequence[tuple[Any, Any]],
) -> tuple[list[tuple[Any, Any]], dict[str, Any]]:
    """Reuse the immutable Cardova source row already present in Robot KB.

    P3 intentionally treats ``source_system.code`` as a global immutable namespace.
    Historical/multisource Cardova observations may therefore already have fixed
    the canonical display name and role.  Reusing those exact values avoids an
    IdempotencyConflict without mutating provenance or inventing a second source.
    """

    row = kb.connection.execute(
        "SELECT name, system_role FROM source_system WHERE code = ?",
        (dry_run.SOURCE_CODE,),
    ).fetchone()
    if row is None:
        return list(prepared), {
            "source_system_reused": False,
            "source_system_mutated": False,
        }

    existing_name = str(row["name"] or "").strip()
    existing_role = str(row["system_role"] or "").strip()
    if not existing_name or not existing_role:
        raise RuntimeError("existing Cardova source_system metadata is malformed")

    aligned: list[tuple[Any, Any]] = []
    for raw, observation in prepared:
        if str(raw.source_code) != dry_run.SOURCE_CODE:
            raise RuntimeError("prepared batch contains a non-Cardova source code")
        aligned.append(
            (
                replace(raw, source_name=existing_name, source_role=existing_role),
                observation,
            )
        )
    return aligned, {
        "source_system_reused": True,
        "source_system_mutated": False,
    }


def _selected_snapshot(kb: KnowledgeBase, native_ids: Sequence[str]) -> dict[str, int]:
    unique_ids = tuple(dict.fromkeys(str(value) for value in native_ids if str(value)))
    if not unique_ids:
        return {
            "sale_transactions": 0,
            "canonical_card_links": 0,
            "hammer_price_jpy_rows": 0,
        }
    placeholders = ",".join("?" for _ in unique_ids)
    params = ("cardova", *unique_ids)
    sales = kb.connection.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM market_observation AS observation
        JOIN source_system AS source ON source.id = observation.source_system_id
        WHERE source.code = ?
          AND observation.source_native_record_id IN ({placeholders})
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND observation.lifecycle_state = 'SEALED'
        """,
        params,
    ).fetchone()["n"]
    canonical = kb.connection.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM market_observation AS observation
        JOIN source_system AS source ON source.id = observation.source_system_id
        WHERE source.code = ?
          AND observation.source_native_record_id IN ({placeholders})
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND observation.canonical_card_id IS NOT NULL
        """,
        params,
    ).fetchone()["n"]
    hammer = kb.connection.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM price_component AS price
        JOIN market_observation AS observation ON observation.id = price.observation_id
        JOIN source_system AS source ON source.id = observation.source_system_id
        WHERE source.code = ?
          AND observation.source_native_record_id IN ({placeholders})
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND price.component_type = 'HAMMER_PRICE'
          AND price.currency = 'JPY'
        """,
        params,
    ).fetchone()["n"]
    return {
        "sale_transactions": int(sales),
        "canonical_card_links": int(canonical),
        "hammer_price_jpy_rows": int(hammer),
    }


def ingest_prepared_batch(
    kb: KnowledgeBase,
    prepared: Sequence[tuple[Any, Any]],
) -> dict[str, Any]:
    """Atomically ingest and validate the selected Cardova sales in one DB tx."""

    if not prepared:
        raise ValueError("no Cardova SALE_TRANSACTION rows are prepared")
    prepared_aligned, source_meta = _reuse_existing_cardova_source_metadata(kb, prepared)
    native_ids = [
        str(observation.source_native_record_id)
        for _raw, observation in prepared_aligned
    ]
    unique_native_ids = tuple(dict.fromkeys(native_ids))
    if len(unique_native_ids) != len(prepared_aligned):
        raise ValueError("duplicate Cardova native IDs in the selected input batch")

    diagnostics = ShadowDiagnostics()
    persistence = ShadowKnowledgePersistence(kb)
    with kb._transaction():
        before = _selected_snapshot(kb, unique_native_ids)
        for raw, observation in prepared_aligned:
            persistence.ingest(raw, (observation,), diagnostics)
        after = _selected_snapshot(kb, unique_native_ids)

        expected = len(unique_native_ids)
        if after["sale_transactions"] != expected:
            raise RuntimeError(
                "postcondition failed: selected Cardova SALE_TRANSACTION count mismatch"
            )
        if after["canonical_card_links"] != 0:
            raise RuntimeError(
                "postcondition failed: Cardova unresolved sales gained canonical links"
            )
        if after["hammer_price_jpy_rows"] != expected:
            raise RuntimeError(
                "postcondition failed: selected Cardova HAMMER_PRICE/JPY count mismatch"
            )
        if (
            diagnostics.sale_transactions_stored
            + diagnostics.duplicate_sale_replays
            != expected
        ):
            raise RuntimeError(
                "postcondition failed: Cardova rows were neither stored nor idempotent replays"
            )

    committed = _selected_snapshot(kb, unique_native_ids)
    if committed != after:
        raise RuntimeError("post-commit verification differs from transactional verification")
    return {
        **source_meta,
        "selected_before": before,
        "selected_after": committed,
        "sale_transactions_stored": int(diagnostics.sale_transactions_stored),
        "duplicate_sale_replays": int(diagnostics.duplicate_sale_replays),
        "unresolved_identities_retained": int(
            diagnostics.unresolved_identities_retained
        ),
        "exact_identities_linked": int(diagnostics.exact_identities_linked),
        "observations_accepted": int(diagnostics.observations_accepted),
        "observations_replayed": int(diagnostics.observations_replayed),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "MANUAL_LOCAL_CARDOVA_PAID_SOLD_P3_INGEST",
        "durable_robot_kb_write": True,
        "local_postgres_only": True,
        "remote_cloud_write_allowed": False,
        "sale_event_semantics": "AUCTION_END_AT_UTC",
        "payment_completion_timestamp_fabricated": False,
        "price_component": "HAMMER_PRICE",
        "currency": "JPY",
        "canonical_identity_claimed": False,
        "commercial_microvariant_claimed": False,
        "exact_identity_eligible": False,
        "source_system_mutated": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(
    records: Sequence[Mapping[str, Any]],
    *,
    database_url: str,
    max_records: int,
    expected_records: int,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    target = validate_local_database_url(database_url)
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    prepared, blocked, selected_count = _prepared_rows(
        records,
        max_records=max_records,
        observed_at=observed,
    )
    if selected_count != expected_records:
        raise ValueError(
            f"selected_records={selected_count} but expected_records={expected_records}"
        )
    if blocked:
        raise ValueError(f"preflight blocked rows: {blocked}")
    if len(prepared) != expected_records:
        raise ValueError(
            f"prepared_sale_transactions={len(prepared)} but expected_records={expected_records}"
        )

    with KnowledgeBase.open(database_url) as kb:
        if kb.backend_name != "postgresql":
            raise RuntimeError("durable Cardova ingest requires PostgreSQL backend")
        result = ingest_prepared_batch(kb, prepared)
    return {
        **target,
        "input_records": len(records),
        "selected_records": selected_count,
        "prepared_sale_transactions": len(prepared),
        "blocked": blocked,
        **result,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Guarded local PostgreSQL ingest for proven Cardova paid SOLD rows"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--expected-records", type=int, required=True)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="required explicit opt-in for durable local PostgreSQL writes",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.expected_records <= args.max_records:
        parser.error("--expected-records must be between 1 and --max-records")

    summary = safe_summary()
    code = 1
    try:
        if not args.commit:
            raise PermissionError("--commit is required for durable Robot KB write")
        database_url = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
        records = dry_run.load_records(args.input)
        summary.update(
            run(
                records,
                database_url=database_url,
                max_records=args.max_records,
                expected_records=args.expected_records,
            )
        )
        summary["committed"] = True
        summary["error"] = None
        code = 0
    except Exception as error:
        summary["committed"] = False
        summary["error"] = f"{type(error).__name__}: {error}"
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
