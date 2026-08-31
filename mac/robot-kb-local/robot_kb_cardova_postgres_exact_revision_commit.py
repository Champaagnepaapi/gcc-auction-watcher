#!/usr/bin/env python3
"""Guarded durable commit path for exact Cardova SALE_TRANSACTION revisions.

This is deliberately separate from PR #209's rollback-only rehearsal.  It reuses
that exact proven cohort/migration/promotion path and adds operator gates required
before a real local PostgreSQL write can occur:

- canonical loopback `robot_pokemon_kb` only;
- explicit `--commit` plus an exact confirmation phrase;
- fresh custom-format pg_dump created before opening the write transaction;
- backup archive readability check and SHA-256 recorded without secrets;
- strict preflight state must match the successful #209 rollback rehearsal shape;
- migration 0003 + all exact `REVISION_OF` promotions in one transaction;
- replay/idempotency and leaf-state checks before COMMIT;
- post-COMMIT verification of schema, registry, exact revisions and PROVEN links.

The script never auto-restores or deletes data.  If a post-COMMIT verification
were to fail, the fresh backup path is retained and surfaced for manual recovery.
No V4 economic activation, notification or commercial action is performed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_postgres_revision_rollback_rehearsal as rehearsal  # noqa: E402
import robot_kb_cardova_print_run_exact_sale_dry_run as print_run  # noqa: E402
import robot_kb_cardova_exact_sale_revision_promotion as promotion  # noqa: E402
import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402

from robot_kb.postgres import connect_postgres  # noqa: E402
from robot_kb.postgres_backup import dump_database  # noqa: E402
from robot_kb.repository import KnowledgeBase  # noqa: E402


EXPECTED_P3_RUNTIME = rehearsal.EXPECTED_P3_RUNTIME
EXPECTED_REHEARSAL_CODE_HEAD = "d6f9c3887bab8af4bdfd05182464dbae36366767"
CONFIRMATION_PHRASE = "I AUTHORIZE CARDOVA DURABLE EXACT SALE WRITE"
DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
MIN_BACKUP_BYTES = 1024
DEFAULT_BACKUP_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "RobotPokemonKB"
    / "backups"
    / "postgres"
)


class DurableCommitError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return print_run.base._norm(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def require_operator_authorization(*, commit: bool, confirmation: str) -> None:
    if not commit:
        raise DurableCommitError("durable write requires explicit --commit")
    if confirmation != CONFIRMATION_PHRASE:
        raise DurableCommitError("durable write confirmation phrase mismatch")


def _backup_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_backup_archive(path: Path) -> Mapping[str, Any]:
    source = path.expanduser().resolve(strict=True)
    stat = source.stat()
    if not source.is_file() or stat.st_size < MIN_BACKUP_BYTES:
        raise DurableCommitError("fresh PostgreSQL backup is missing or implausibly small")
    pg_restore = shutil.which("pg_restore")
    if pg_restore is None:
        raise DurableCommitError("pg_restore is required to validate the fresh backup")
    completed = subprocess.run(
        [pg_restore, "--list", str(source)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        raise DurableCommitError("fresh PostgreSQL backup is not a readable custom archive")
    return {
        "backup_path": str(source),
        "backup_bytes": int(stat.st_size),
        "backup_sha256": _backup_sha256(source),
        "backup_archive_readable": True,
    }


def create_and_validate_fresh_backup(database_url: str, backup_directory: Path) -> Mapping[str, Any]:
    path = dump_database(database_url, backup_directory)
    return validate_backup_archive(path)


def _compose_plans(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Any], Mapping[Any, Mapping[str, str]], Mapping[str, Any]]:
    sales, identities, cohort = rehearsal._compose_exact_cohort(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
    )
    if len(sales) != len(identities) or not sales:
        raise DurableCommitError("exact durable cohort is empty or misjoined")
    plans = []
    for sale, identity in zip(sales, identities):
        plan, reason = print_run.canonical_plan(identity, sale)
        if plan is None:
            raise DurableCommitError(f"exact cohort became unrepresentable: {reason}")
        plans.append(plan)
    family_applicability = print_run.base._family_applicability(plans)
    source_ids = [plan.source_native_record_id for plan in plans]
    if len(source_ids) != len(set(source_ids)):
        raise DurableCommitError("exact durable cohort contains duplicate source ids")
    return sales, identities, plans, family_applicability, cohort


def _assert_preflight(connection: Any, source_ids: Sequence[str]) -> Mapping[str, Any]:
    versions = rehearsal._validate_applied_catalog(connection)
    if versions != [1, 2]:
        raise DurableCommitError(f"durable schema must start at [1,2], got {versions}")
    registry = rehearsal._print_run_registry_snapshot(connection)
    targets = rehearsal._target_snapshot(connection, source_ids)
    if targets["exact_revision_count"] != 0:
        raise DurableCommitError("target cohort already has durable exact leaf revisions")
    if targets["proven_identifier_count"] != 0:
        raise DurableCommitError("target cohort already has durable PROVEN Cardova identifiers")
    bad = {
        source_id: state
        for source_id, state in targets["sources"].items()
        if state != {"unresolved": 1, "exact": 0, "total": 1}
    }
    if bad:
        raise DurableCommitError(f"target durable leaf baseline differs: {bad}")
    return {
        "schema_versions": versions,
        "registry": registry,
        "targets": targets,
    }


def _apply_and_verify_inside_transaction(
    connection: Any,
    sales: Sequence[Mapping[str, Any]],
    identities: Sequence[Mapping[str, Any]],
    plans: Sequence[Any],
    family_applicability: Mapping[Any, Mapping[str, str]],
) -> Mapping[str, Any]:
    source_ids = [plan.source_native_record_id for plan in plans]
    rehearsal._apply_migration_3_without_commit(connection)
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
            raise DurableCommitError(
                f"unexpected first-pass replay for {result.source_native_record_id}"
            )
        first_results.append(result)

    inside_targets = rehearsal._target_snapshot(connection, source_ids)
    bad_inside = {
        source_id: state
        for source_id, state in inside_targets["sources"].items()
        if state != {"unresolved": 0, "exact": 1, "total": 1}
    }
    if bad_inside:
        raise DurableCommitError(f"transactional exact leaf verification failed: {bad_inside}")
    expected = len(source_ids)
    if inside_targets["exact_revision_count"] != expected:
        raise DurableCommitError("transactional exact revision count mismatch")
    if inside_targets["proven_identifier_count"] != expected:
        raise DurableCommitError("transactional PROVEN identifier count mismatch")

    revision_ids = {
        result.source_native_record_id: result.revision_observation_id
        for result in first_results
    }
    replayed = 0
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
            raise DurableCommitError(
                f"second pass created duplicate for {result.source_native_record_id}"
            )
        if revision_ids[result.source_native_record_id] != result.revision_observation_id:
            raise DurableCommitError("replay revision id changed")
        replayed += 1

    after_replay = rehearsal._target_snapshot(connection, source_ids)
    if after_replay != inside_targets:
        raise DurableCommitError("replay changed target leaf state")
    versions = [
        int(row["version"])
        for row in rehearsal._applied_migrations(connection)
    ]
    if versions != [1, 2, 3]:
        raise DurableCommitError(f"transaction schema versions differ: {versions}")

    return {
        "target_count": expected,
        "exact_revision_rows": inside_targets["exact_revision_count"],
        "proven_identifier_links": inside_targets["proven_identifier_count"],
        "distinct_canonical_cards": len(
            {result.canonical_card_id for result in first_results}
        ),
        "replay_exact_matches": replayed,
        "transaction_schema_versions": versions,
    }


def _verify_post_commit(connection: Any, source_ids: Sequence[str]) -> Mapping[str, Any]:
    versions = rehearsal._validate_applied_catalog(connection)
    if versions != [1, 2, 3]:
        raise DurableCommitError(f"post-commit schema versions differ: {versions}")
    registry = rehearsal._print_run_registry_snapshot(connection)
    codes = {row["code"] for row in registry["values"]}
    if not {"UNKNOWN", "NO_RARITY_SYMBOL", "RARITY_SYMBOL_PRESENT"}.issubset(codes):
        raise DurableCommitError("post-commit print_run registry is incomplete")
    targets = rehearsal._target_snapshot(connection, source_ids)
    expected = len(source_ids)
    bad = {
        source_id: state
        for source_id, state in targets["sources"].items()
        if state != {"unresolved": 0, "exact": 1, "total": 1}
    }
    if bad:
        raise DurableCommitError(f"post-commit exact leaf verification failed: {bad}")
    if targets["exact_revision_count"] != expected:
        raise DurableCommitError("post-commit exact revision count mismatch")
    if targets["proven_identifier_count"] != expected:
        raise DurableCommitError("post-commit PROVEN identifier count mismatch")
    return {
        "schema_versions": versions,
        "exact_revision_rows": targets["exact_revision_count"],
        "proven_identifier_links": targets["proven_identifier_count"],
        "target_count": expected,
    }


def run_durable_commit(
    database_url: str,
    *,
    commit: bool,
    confirmation: str,
    backup_directory: Path = DEFAULT_BACKUP_DIR,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_groups: int = 20,
    min_distinct_dexids: int = 2,
    timeout_seconds: float = 4.0,
) -> Mapping[str, Any]:
    require_operator_authorization(commit=commit, confirmation=confirmation)
    target = recovery.validate_local_database_url(database_url)

    # Compose against read-only snapshots before creating a backup or entering
    # the write transaction. Identity ambiguity remains fail-closed here.
    sales, identities, plans, family_applicability, cohort = _compose_plans(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
    )
    source_ids = [plan.source_native_record_id for plan in plans]

    backup = create_and_validate_fresh_backup(database_url, backup_directory)
    connection = connect_postgres(database_url)
    committed = False
    preflight: Mapping[str, Any] = {}
    inside: Mapping[str, Any] = {}
    try:
        preflight = _assert_preflight(connection, source_ids)
        connection.execute("BEGIN")
        connection.execute(
            "SELECT pg_advisory_xact_lock(?)",
            (rehearsal.LOCK_KEY,),
        )
        inside = _apply_and_verify_inside_transaction(
            connection,
            sales,
            identities,
            plans,
            family_applicability,
        )
        connection.execute("COMMIT")
        committed = True
        post = _verify_post_commit(connection, source_ids)
        return {
            **target,
            **cohort,
            "p3_runtime_required": EXPECTED_P3_RUNTIME,
            "rehearsal_code_head_required": EXPECTED_REHEARSAL_CODE_HEAD,
            **backup,
            "before_schema_versions": preflight["schema_versions"],
            "inside_transaction": inside,
            "commit_executed": True,
            "post_commit": post,
            "recovery_required": False,
            "v4_use": False,
        }
    except Exception as error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if committed:
            raise DurableCommitError(
                f"post-commit verification failed; manual recovery may be required; "
                f"backup retained at {backup['backup_path']}: {type(error).__name__}: {error}"
            ) from error
        raise
    finally:
        connection.close()


def safe_summary() -> Mapping[str, Any]:
    return {
        "mode": "GUARDED_CARDOVA_POSTGRES_EXACT_REVISION_COMMIT",
        "explicit_commit_required": True,
        "exact_confirmation_required": True,
        "fresh_backup_required": True,
        "backup_archive_validation_required": True,
        "single_transaction": True,
        "post_commit_verification_required": True,
        "auto_restore": False,
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
        description="Guarded durable Cardova exact-sale revision commit"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--backup-directory", type=Path, default=DEFAULT_BACKUP_DIR)
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
            run_durable_commit(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                commit=args.commit,
                confirmation=args.confirm,
                backup_directory=args.backup_directory,
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
