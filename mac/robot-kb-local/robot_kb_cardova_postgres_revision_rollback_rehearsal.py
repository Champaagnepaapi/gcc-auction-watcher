#!/usr/bin/env python3
"""Rollback-only PostgreSQL rehearsal for exact Cardova sale revisions.

This script has deliberately no commit path. It reads the exact Cardova cohort
first, opens the loopback PostgreSQL database, begins one outer transaction,
applies only the validated #207 PostgreSQL migration inside that transaction,
promotes the exact sales through append-only REVISION_OF observations, verifies
prices/provenance/idempotency, and then rolls the entire transaction back.

A process disconnect before the explicit rollback is also transaction-safe:
psycopg closes an uncommitted PostgreSQL transaction without committing it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402
import robot_kb_cardova_print_run_live_validation as live  # noqa: E402
import robot_kb_cardova_print_run_exact_sale_dry_run as print_run  # noqa: E402
import robot_kb_cardova_exact_sale_revision_promotion as promotion  # noqa: E402

from robot_kb.postgres import (  # noqa: E402
    POSTGRES_MIGRATION_DIRECTORY,
    _migration_catalog,
    connect_postgres,
)
from robot_kb.repository import KnowledgeBase  # noqa: E402


EXPECTED_P3_RUNTIME = "38288a950db8285bcbf279d91354f8a1ad3a8c2f"
MIGRATION_VERSION = 3
MIGRATION_FILENAME = "0003_print_run_rarity_symbol.sql"
DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
LOCK_KEY = 76003310720820260831


class RehearsalError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return print_run.base._norm(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _applied_migrations(connection: Any) -> list[Mapping[str, Any]]:
    return list(
        connection.execute(
            """
            SELECT version, filename, checksum_sha256
            FROM schema_migration ORDER BY version
            """
        ).fetchall()
    )


def _validate_applied_catalog(connection: Any) -> list[int]:
    rows = _applied_migrations(connection)
    catalog = _migration_catalog()
    versions = [int(row["version"]) for row in rows]
    for row in rows:
        version = int(row["version"])
        entry = catalog.get(version)
        if entry is None:
            raise RehearsalError(f"applied migration {version} has no #207 runtime file")
        path, checksum = entry
        if row["filename"] != path.name or row["checksum_sha256"] != checksum:
            raise RehearsalError(f"applied migration {version} differs from #207 runtime")
    return versions


def _print_run_registry_snapshot(connection: Any) -> Mapping[str, Any]:
    dimensions = connection.execute(
        """
        SELECT id, code, name FROM variant_dimension
        WHERE id = 'vdim_print_run' OR code = 'print_run'
        ORDER BY id
        """
    ).fetchall()
    values = connection.execute(
        """
        SELECT value.id, value.dimension_id, value.code, value.label
        FROM variant_value AS value
        JOIN variant_dimension AS dimension ON dimension.id = value.dimension_id
        WHERE dimension.id = 'vdim_print_run' OR dimension.code = 'print_run'
        ORDER BY value.id
        """
    ).fetchall()
    return {
        "dimensions": [dict(row) for row in dimensions],
        "values": [dict(row) for row in values],
    }


def _target_snapshot(connection: Any, source_ids: Sequence[str]) -> Mapping[str, Any]:
    if not source_ids:
        return {"sources": {}, "exact_revision_count": 0, "proven_identifier_count": 0}
    sources: dict[str, Mapping[str, int]] = {}
    exact_revisions = 0
    proven_identifiers = 0
    for source_id in sorted(source_ids):
        leaf = connection.execute(
            """
            SELECT
              SUM(CASE WHEN observation.canonical_card_id IS NULL THEN 1 ELSE 0 END) AS unresolved,
              SUM(CASE WHEN observation.canonical_card_id IS NOT NULL THEN 1 ELSE 0 END) AS exact,
              COUNT(*) AS total
            FROM market_observation AS observation
            JOIN source_system AS source ON source.id = observation.source_system_id
            WHERE source.code = 'cardova'
              AND observation.source_native_record_id = ?
              AND observation.observation_type = 'SALE_TRANSACTION'
              AND observation.lifecycle_state = 'SEALED'
              AND NOT EXISTS (
                  SELECT 1
                  FROM observation_relationship AS relationship
                  JOIN market_observation AS revision
                    ON revision.id = relationship.from_observation_id
                  WHERE relationship.to_observation_id = observation.id
                    AND relationship.relationship_type = 'REVISION_OF'
                    AND revision.lifecycle_state = 'SEALED'
              )
            """,
            (source_id,),
        ).fetchone()
        state = {
            "unresolved": int(leaf["unresolved"] or 0),
            "exact": int(leaf["exact"] or 0),
            "total": int(leaf["total"] or 0),
        }
        sources[source_id] = state
        exact_revisions += state["exact"]
        proven_identifiers += int(
            connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM identifier_link AS link
                JOIN external_identifier AS identifier
                  ON identifier.id = link.external_identifier_id
                JOIN external_object AS object
                  ON object.id = identifier.external_object_id
                JOIN source_system AS source ON source.id = object.source_system_id
                WHERE source.code = 'cardova'
                  AND object.source_native_id = ?
                  AND identifier.namespace = 'CARDOVA_AUCTION_ULID'
                  AND link.resolution_state = 'PROVEN'
                  AND link.canonical_card_id IS NOT NULL
                """,
                (source_id,),
            ).fetchone()["n"]
        )
    return {
        "sources": sources,
        "exact_revision_count": exact_revisions,
        "proven_identifier_count": proven_identifiers,
    }


def _apply_migration_3_without_commit(connection: Any) -> None:
    versions = _validate_applied_catalog(connection)
    if versions != [1, 2]:
        raise RehearsalError(f"expected durable PostgreSQL schema [1, 2], got {versions}")
    catalog = _migration_catalog()
    path, checksum = catalog[MIGRATION_VERSION]
    if path.name != MIGRATION_FILENAME:
        raise RehearsalError("#207 migration filename mismatch")
    script = path.read_text(encoding="utf-8")
    if hashlib.sha256(script.encode("utf-8")).hexdigest() != checksum:
        raise RehearsalError("#207 migration checksum changed while rehearsing")
    connection.executescript(script)
    connection.execute(
        """
        INSERT INTO schema_migration(version, filename, checksum_sha256, applied_at)
        VALUES (?, ?, ?, ?)
        """,
        (MIGRATION_VERSION, path.name, checksum, _now()),
    )
    inside_versions = [int(row["version"]) for row in _applied_migrations(connection)]
    if inside_versions != [1, 2, 3]:
        raise RehearsalError(f"transactional migration did not reach [1,2,3]: {inside_versions}")
    registry = _print_run_registry_snapshot(connection)
    codes = {row["code"] for row in registry["values"]}
    if not {"UNKNOWN", "NO_RARITY_SYMBOL", "RARITY_SYMBOL_PRESENT"}.issubset(codes):
        raise RehearsalError("transactional print_run registry is incomplete")


def _compose_exact_cohort(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], Mapping[str, Any]]:
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    sales = [row for row in selected.get("records", []) if isinstance(row, Mapping)]
    identity = live.compose_exact_identity_rows(
        sales,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
    )
    identities = [row for row in identity.get("records", []) if isinstance(row, Mapping)]
    sale_by_id = {_norm(row.get("source_native_record_id")): row for row in sales}
    identity_by_id = {_norm(row.get("source_native_record_id")): row for row in identities}
    if "" in sale_by_id or "" in identity_by_id:
        raise RehearsalError("cohort contains missing source ids")
    if len(identity_by_id) != len(identities):
        raise RehearsalError("exact identity cohort contains duplicate source ids")
    exact_sales = [sale_by_id[source_id] for source_id in sorted(identity_by_id)]
    return exact_sales, [identity_by_id[_norm(row.get("source_native_record_id"))] for row in exact_sales], {
        "unresolved_cardova_sales_available": int(selected.get("unresolved_sale_transactions_available", 0)),
        "selected_sales": len(sales),
        "exact_identity_rows": len(identities),
        "identity_blocked_count": int(identity.get("identity_blocked_count", 0)),
        "identity_blocked": dict(identity.get("identity_blocked") or {}),
    }


def run_rehearsal(
    database_url: str,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_groups: int = 20,
    min_distinct_dexids: int = 2,
    timeout_seconds: float = 4.0,
) -> Mapping[str, Any]:
    target = recovery.validate_local_database_url(database_url)
    sales, identities, cohort = _compose_exact_cohort(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
    )
    if len(sales) != len(identities) or not sales:
        raise RehearsalError("exact rehearsal cohort is empty or misjoined")

    plans = []
    for sale, identity in zip(sales, identities):
        plan, reason = print_run.canonical_plan(identity, sale)
        if plan is None:
            raise RehearsalError(f"exact cohort became unrepresentable: {reason}")
        plans.append(plan)
    family_applicability = print_run.base._family_applicability(plans)
    source_ids = [plan.source_native_record_id for plan in plans]

    connection = connect_postgres(database_url)
    rollback_executed = False
    inside_summary: dict[str, Any] = {}
    before_versions: list[int] = []
    before_registry: Mapping[str, Any] = {}
    before_targets: Mapping[str, Any] = {}
    try:
        before_versions = _validate_applied_catalog(connection)
        if before_versions != [1, 2]:
            raise RehearsalError(f"durable schema must start at [1,2], got {before_versions}")
        before_registry = _print_run_registry_snapshot(connection)
        before_targets = _target_snapshot(connection, source_ids)
        if before_targets["exact_revision_count"] != 0:
            raise RehearsalError("target cohort already has durable exact leaf revisions")
        if before_targets["proven_identifier_count"] != 0:
            raise RehearsalError("target cohort already has durable PROVEN Cardova identifiers")
        bad_before = {
            source_id: state
            for source_id, state in before_targets["sources"].items()
            if state != {"unresolved": 1, "exact": 0, "total": 1}
        }
        if bad_before:
            raise RehearsalError(f"target durable leaf baseline differs: {bad_before}")

        connection.execute("BEGIN")
        connection.execute("SELECT pg_advisory_xact_lock(?)", (LOCK_KEY,))
        _apply_migration_3_without_commit(connection)
        kb = KnowledgeBase(connection)
        revision_time = _now()

        first_results = []
        for sale, identity, plan in zip(sales, identities, plans):
            result = promotion.promote_existing_sale(
                kb,
                identity,
                sale,
                plan=plan,
                family_applicability=family_applicability[print_run.base._family_key(plan)],
                revision_observed_at=revision_time,
            )
            if result.replayed:
                raise RehearsalError(f"unexpected first-pass replay for {result.source_native_record_id}")
            first_results.append(result)

        inside_targets = _target_snapshot(connection, source_ids)
        bad_inside = {
            source_id: state
            for source_id, state in inside_targets["sources"].items()
            if state != {"unresolved": 0, "exact": 1, "total": 1}
        }
        if bad_inside:
            raise RehearsalError(f"transactional exact leaf verification failed: {bad_inside}")
        if inside_targets["exact_revision_count"] != len(source_ids):
            raise RehearsalError("transactional exact revision count mismatch")
        if inside_targets["proven_identifier_count"] != len(source_ids):
            raise RehearsalError("transactional PROVEN identifier count mismatch")

        replayed = 0
        revision_ids = {result.source_native_record_id: result.revision_observation_id for result in first_results}
        for sale, identity, plan in zip(sales, identities, plans):
            result = promotion.promote_existing_sale(
                kb,
                identity,
                sale,
                plan=plan,
                family_applicability=family_applicability[print_run.base._family_key(plan)],
                revision_observed_at=_now(),
            )
            if not result.replayed:
                raise RehearsalError(f"second pass created duplicate for {result.source_native_record_id}")
            if revision_ids[result.source_native_record_id] != result.revision_observation_id:
                raise RehearsalError("replay revision id changed")
            replayed += 1

        after_replay = _target_snapshot(connection, source_ids)
        if after_replay != inside_targets:
            raise RehearsalError("replay changed target leaf state")

        canonical_ids = {result.canonical_card_id for result in first_results}
        inside_summary = {
            "transaction_schema_versions": [int(row["version"]) for row in _applied_migrations(connection)],
            "exact_revision_rows": inside_targets["exact_revision_count"],
            "proven_identifier_links": inside_targets["proven_identifier_count"],
            "distinct_canonical_cards": len(canonical_ids),
            "replay_exact_matches": replayed,
            "target_count": len(source_ids),
        }
        connection.execute("ROLLBACK")
        rollback_executed = True

        after_versions = _validate_applied_catalog(connection)
        after_registry = _print_run_registry_snapshot(connection)
        after_targets = _target_snapshot(connection, source_ids)
        if after_versions != before_versions:
            raise RehearsalError("schema migration ledger changed after rollback")
        if after_registry != before_registry:
            raise RehearsalError("print_run registry changed after rollback")
        if after_targets != before_targets:
            raise RehearsalError("target durable Cardova state changed after rollback")

        return {
            **target,
            **cohort,
            "p3_runtime_required": EXPECTED_P3_RUNTIME,
            "before_schema_versions": before_versions,
            "inside_transaction": inside_summary,
            "rollback_executed": rollback_executed,
            "after_schema_versions": after_versions,
            "migration_registry_restored": True,
            "target_durable_state_restored": True,
            "durable_exact_revisions_after_rollback": after_targets["exact_revision_count"],
            "durable_proven_identifiers_after_rollback": after_targets["proven_identifier_count"],
            "local_postgres_durable_write": False,
        }
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
            rollback_executed = True
        raise
    finally:
        connection.close()


def safe_summary() -> Mapping[str, Any]:
    return {
        "mode": "ROLLBACK_ONLY_CARDOVA_POSTGRES_EXACT_REVISION_REHEARSAL",
        "outer_transaction_required": True,
        "commit_path_exposed": False,
        "migration_3_applied_transactionally_only": True,
        "append_only_revision_promotion": True,
        "sealed_original_updated": False,
        "rollback_verification_required": True,
        "local_postgres_durable_write": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rollback-only PostgreSQL rehearsal for Cardova exact sale revisions"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=20)
    parser.add_argument("--min-distinct-dexids", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=4.0)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.max_groups <= 50:
        parser.error("--max-groups must be between 1 and 50")
    if not 2 <= args.min_distinct_dexids <= 20:
        parser.error("--min-distinct-dexids must be between 2 and 20")
    if not 0.5 <= args.timeout_seconds <= 10.0:
        parser.error("--timeout-seconds must be between 0.5 and 10")

    payload = dict(safe_summary())
    code = 1
    try:
        payload.update(
            run_rehearsal(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
                timeout_seconds=args.timeout_seconds,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
