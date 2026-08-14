"""Lossless, restartable SQLite-to-PostgreSQL pilot transfer and verification."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .migrations import _migration_catalog as _sqlite_migration_catalog
from .postgres import is_postgres_url
from .repository import KnowledgeBase
from .sidecar.models import RawSourceRecord, ShadowDiagnostics
from .sidecar.normalizers import normalize_gcc, normalize_tcgdex
from .sidecar.persistence import ShadowKnowledgePersistence


DEFAULT_PILOT = Path.home() / "robot-pokemon-data/shadow-pilot-2026-08-14.sqlite"


class PilotMigrationError(RuntimeError):
    pass


class PilotMigrationConflict(PilotMigrationError):
    pass


TABLE_KEYS: Mapping[str, Tuple[str, ...]] = {
    "source_system": ("id",),
    "variant_dimension": ("id",),
    "variant_value": ("id",),
    "variant_profile": ("id",),
    "variant_assignment": ("profile_id", "dimension_id"),
    "canonical_set": ("id",),
    "card_family": ("id",),
    "localized_card": ("id",),
    "family_variant_applicability": ("id",),
    "allowed_variant_combination": ("id",),
    "canonical_card": ("id",),
    "external_object": ("id",),
    "external_identifier": ("id",),
    "identifier_link": ("id",),
    "card_alias": ("id",),
    "source_payload": ("payload_sha256",),
    "source_record": ("id",),
    "source_record_payload": ("source_record_id",),
    "source_record_retrieval": ("id",),
    "identity_subject": ("id",),
    "identity_resolution": ("id",),
    "identity_candidate": ("id",),
    "field_claim": ("id",),
    "field_resolution": ("id",),
    "collectible_instance": ("id",),
    "market_observation": ("id",),
    "sale_transaction": ("observation_id",),
    "listing_snapshot": ("observation_id",),
    "provider_metric_observation": ("observation_id",),
    "population_observation": ("observation_id",),
    "fx_rate_observation": ("observation_id",),
    "price_component": ("id",),
    "fx_normalization": ("id",),
    "observation_relationship": ("id",),
    "observation_identity_link": ("id",),
}

PRE_PROFILE_TABLES = (
    "source_system",
    "variant_dimension",
    "variant_value",
)

POST_PROFILE_TABLES = (
    "canonical_set",
    "card_family",
    "localized_card",
    "family_variant_applicability",
    "allowed_variant_combination",
    "canonical_card",
    "external_object",
    "external_identifier",
    "identifier_link",
    "card_alias",
    "source_payload",
    "source_record",
    "source_record_payload",
    "source_record_retrieval",
    "identity_subject",
)

POST_IDENTITY_TABLES = (
    "identity_candidate",
    "field_claim",
    "collectible_instance",
)

OBSERVATION_CHILD_TABLES = (
    "sale_transaction",
    "listing_snapshot",
    "provider_metric_observation",
    "population_observation",
    "fx_rate_observation",
    "price_component",
    "fx_normalization",
    "observation_identity_link",
)

CRITICAL_TABLES = (
    "source_payload",
    "source_record",
    "source_record_retrieval",
    "external_object",
    "market_observation",
    "listing_snapshot",
    "sale_transaction",
    "provider_metric_observation",
    "field_claim",
    "identity_resolution",
    "observation_identity_link",
)


def sqlite_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(
        f"file:{resolved}?mode=ro", uri=True, isolation_level=None
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise PilotMigrationError("SQLite pilot could not be forced read-only")
    violation = connection.execute("PRAGMA foreign_key_check").fetchone()
    if violation is not None:
        connection.close()
        raise PilotMigrationError(
            f"SQLite pilot contains a foreign-key violation: {tuple(violation)}"
        )
    catalog = _sqlite_migration_catalog()
    try:
        ledger = connection.execute(
            """
            SELECT version, filename, checksum_sha256
            FROM schema_migration ORDER BY version
            """
        ).fetchall()
    except sqlite3.Error as exc:
        connection.close()
        raise PilotMigrationError("SQLite pilot has no valid migration ledger") from exc
    if [row["version"] for row in ledger] != sorted(catalog):
        connection.close()
        raise PilotMigrationError("SQLite pilot migration versions are incomplete")
    for row in ledger:
        migration_path, checksum = catalog[row["version"]]
        if row["filename"] != migration_path.name or row["checksum_sha256"] != checksum:
            connection.close()
            raise PilotMigrationError(
                f"SQLite pilot migration {row['version']} checksum differs"
            )
    return connection


def _columns(source: sqlite3.Connection, table: str) -> Tuple[str, ...]:
    columns = tuple(
        row["name"]
        for row in source.execute(f'PRAGMA table_info("{table}")').fetchall()
    )
    if not columns:
        raise PilotMigrationError(f"SQLite pilot is missing table {table}")
    return columns


def _source_rows(
    source: sqlite3.Connection, table: str
) -> List[Dict[str, Any]]:
    columns = _columns(source, table)
    order = ", ".join(TABLE_KEYS[table])
    selected = ", ".join(columns)
    return [
        dict(row)
        for row in source.execute(
            f'SELECT {selected} FROM "{table}" ORDER BY {order}'
        ).fetchall()
    ]


def _normal(value: Any) -> Any:
    if isinstance(value, memoryview):
        return value.tobytes()
    return value


def _same(left: Mapping[str, Any], right: Mapping[str, Any], columns: Sequence[str]) -> bool:
    return all(_normal(left[column]) == _normal(right[column]) for column in columns)


def _existing(
    destination: Any,
    table: str,
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> Optional[Mapping[str, Any]]:
    key_columns = TABLE_KEYS[table]
    where = " AND ".join(f"{column} = ?" for column in key_columns)
    values = tuple(row[column] for column in key_columns)
    return destination.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {where}", values
    ).fetchone()


def _insert_equal(
    destination: Any,
    table: str,
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> bool:
    existing = _existing(destination, table, row, columns)
    if existing is not None:
        if not _same(existing, row, columns):
            key = tuple(row[column] for column in TABLE_KEYS[table])
            raise PilotMigrationConflict(
                f"destination {table} row {key!r} differs from SQLite"
            )
        return False
    placeholders = ", ".join("?" for _ in columns)
    try:
        destination.execute(
            f"INSERT INTO {table}({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row[column] for column in columns),
        )
    except Exception as exc:
        key = tuple(row[column] for column in TABLE_KEYS[table])
        raise PilotMigrationConflict(
            f"destination rejected {table} row {key!r}; transaction rolled back"
        ) from exc
    return True


def _topological_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_column: str,
    dependencies: Mapping[str, Iterable[Optional[str]]],
) -> List[Mapping[str, Any]]:
    remaining = {str(row[id_column]): row for row in rows}
    ordered: List[Mapping[str, Any]] = []
    completed: set[str] = set()
    source_ids = set(remaining)
    while remaining:
        ready = [
            row
            for row_id, row in remaining.items()
            if all(
                dependency is None
                or dependency not in source_ids
                or dependency in completed
                for dependency in dependencies.get(row_id, ())
            )
        ]
        if not ready:
            raise PilotMigrationError(
                f"cyclic or unresolved dependency in {id_column} row stream"
            )
        ready.sort(key=lambda row: (str(row.get("created_at", "")), str(row[id_column])))
        for row in ready:
            row_id = str(row[id_column])
            ordered.append(row)
            completed.add(row_id)
            del remaining[row_id]
    return ordered


def _copy_regular_table(
    source: sqlite3.Connection, destination: Any, table: str
) -> int:
    columns = _columns(source, table)
    return sum(
        _insert_equal(destination, table, row, columns)
        for row in _source_rows(source, table)
    )


def _copy_variant_profiles(
    source: sqlite3.Connection, destination: Any
) -> int:
    table = "variant_profile"
    columns = _columns(source, table)
    inserted = 0
    rows = _source_rows(source, table)
    for row in rows:
        existing = _existing(destination, table, row, columns)
        if existing is not None and _same(existing, row, columns):
            continue
        staged = dict(row)
        staged["locked_at"] = None
        staged["semantic_key"] = None
        if existing is not None and not _same(existing, staged, columns):
            raise PilotMigrationConflict(
                f"destination variant_profile {(row['id'],)!r} differs from SQLite"
            )
        if existing is None:
            _insert_equal(destination, table, staged, columns)
            inserted += 1
    inserted += _copy_regular_table(source, destination, "variant_assignment")
    for row in rows:
        if row["locked_at"] is None and row["semantic_key"] is None:
            continue
        destination.execute(
            """
            UPDATE variant_profile SET semantic_key = ?, locked_at = ?
            WHERE id = ? AND locked_at IS NULL AND semantic_key IS NULL
            """,
            (row["semantic_key"], row["locked_at"], row["id"]),
        )
        final = _existing(destination, table, row, columns)
        if final is None or not _same(final, row, columns):
            raise PilotMigrationConflict(
                f"destination variant_profile {(row['id'],)!r} could not be sealed"
            )
    return inserted


def _copy_dependency_table(
    source: sqlite3.Connection,
    destination: Any,
    table: str,
    id_column: str,
    dependency_column: str,
) -> int:
    columns = _columns(source, table)
    rows = _source_rows(source, table)
    dependencies = {
        str(row[id_column]): (row[dependency_column],) for row in rows
    }
    return sum(
        _insert_equal(destination, table, row, columns)
        for row in _topological_rows(
            rows, id_column=id_column, dependencies=dependencies
        )
    )


def _copy_observations(
    source: sqlite3.Connection, destination: Any
) -> int:
    observation_columns = _columns(source, "market_observation")
    observations = _source_rows(source, "market_observation")
    child_rows = {
        table: _source_rows(source, table) for table in OBSERVATION_CHILD_TABLES
    }
    by_observation: MutableMapping[str, MutableMapping[str, List[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for table, rows in child_rows.items():
        for row in rows:
            by_observation[str(row["observation_id"])][table].append(row)

    revision_rows = {
        str(row["from_observation_id"]): row
        for row in _source_rows(source, "observation_relationship")
        if row["relationship_type"] == "REVISION_OF"
    }
    dependencies: Dict[str, List[Optional[str]]] = {}
    for row in observations:
        row_id = str(row["id"])
        dependency_list: List[Optional[str]] = [row["revision_of_observation_id"]]
        dependency_list.extend(
            normalization["rate_observation_id"]
            for normalization in by_observation[row_id]["fx_normalization"]
        )
        dependencies[row_id] = dependency_list

    inserted = 0
    for row in _topological_rows(
        observations, id_column="id", dependencies=dependencies
    ):
        row_id = str(row["id"])
        existing = _existing(
            destination, "market_observation", row, observation_columns
        )
        final_exists = existing is not None and _same(existing, row, observation_columns)
        staged = dict(row)
        staged["lifecycle_state"] = "DRAFT"
        staged["sealed_at"] = None
        if existing is not None and not final_exists and not _same(
            existing, staged, observation_columns
        ):
            raise PilotMigrationConflict(
                f"destination market_observation {(row_id,)!r} differs from SQLite"
            )
        if existing is None:
            _insert_equal(
                destination, "market_observation", staged, observation_columns
            )
            inserted += 1

        for table in OBSERVATION_CHILD_TABLES:
            columns = _columns(source, table)
            for child in by_observation[row_id][table]:
                inserted += _insert_equal(destination, table, child, columns)

        revision = revision_rows.get(row_id)
        if revision is not None:
            columns = _columns(source, "observation_relationship")
            inserted += _insert_equal(
                destination, "observation_relationship", revision, columns
            )
        elif row["revision_of_observation_id"] is not None:
            raise PilotMigrationError(
                f"observation {row_id!r} has no matching REVISION_OF relationship"
            )

        if not final_exists and row["lifecycle_state"] == "SEALED":
            destination.execute(
                """
                UPDATE market_observation
                SET lifecycle_state = 'SEALED', sealed_at = ?
                WHERE id = ? AND lifecycle_state = 'DRAFT'
                """,
                (row["sealed_at"], row_id),
            )
        final = _existing(
            destination, "market_observation", row, observation_columns
        )
        if final is None or not _same(final, row, observation_columns):
            raise PilotMigrationConflict(
                f"destination market_observation {(row_id,)!r} could not be finalized"
            )

    relationship_columns = _columns(source, "observation_relationship")
    for relationship in _source_rows(source, "observation_relationship"):
        if relationship["relationship_type"] == "REVISION_OF":
            continue
        inserted += _insert_equal(
            destination,
            "observation_relationship",
            relationship,
            relationship_columns,
        )
    return inserted


def migrate_sqlite_to_database(
    sqlite_path: Path,
    destination: KnowledgeBase,
    *,
    require_postgres: bool = True,
) -> Mapping[str, Any]:
    if require_postgres and destination.backend_name != "postgresql":
        raise PilotMigrationError("pilot destination must be PostgreSQL")
    source = open_sqlite_read_only(sqlite_path)
    inserted = 0
    try:
        with destination._transaction():
            for table in PRE_PROFILE_TABLES:
                inserted += _copy_regular_table(source, destination.connection, table)
            # Profile assignments must be copied before the one permitted lock
            # transition; supersession chains require deterministic dependency order.
            inserted += _copy_variant_profiles(source, destination.connection)
            for table in POST_PROFILE_TABLES:
                inserted += _copy_regular_table(source, destination.connection, table)
            inserted += _copy_dependency_table(
                source,
                destination.connection,
                "identity_resolution",
                "id",
                "supersedes_resolution_id",
            )
            for table in POST_IDENTITY_TABLES:
                inserted += _copy_regular_table(source, destination.connection, table)
            inserted += _copy_dependency_table(
                source,
                destination.connection,
                "field_resolution",
                "id",
                "supersedes_resolution_id",
            )
            inserted += _copy_observations(source, destination.connection)
    finally:
        source.close()
    return {
        "sqlite_sha256": sqlite_checksum(sqlite_path),
        "rows_inserted": inserted,
    }


def _json_value(value: Any) -> Any:
    value = _normal(value)
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    return value


def _fingerprint_rows(
    rows: Iterable[Mapping[str, Any]], columns: Sequence[str]
) -> str:
    digest = hashlib.sha256()
    for row in rows:
        serialized = json.dumps(
            [_json_value(row[column]) for column in columns],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(serialized).to_bytes(8, "big"))
        digest.update(serialized)
    return digest.hexdigest()


def _destination_rows(
    destination: Any, table: str, columns: Sequence[str]
) -> List[Mapping[str, Any]]:
    return destination.execute(
        f"SELECT {', '.join(columns)} FROM {table} "
        f"ORDER BY {', '.join(TABLE_KEYS[table])}"
    ).fetchall()


def verify_sqlite_against_database(
    sqlite_path: Path, destination: KnowledgeBase
) -> Mapping[str, Any]:
    source = open_sqlite_read_only(sqlite_path)
    try:
        counts: Dict[str, int] = {}
        fingerprints: Dict[str, str] = {}
        for table in TABLE_KEYS:
            columns = _columns(source, table)
            sqlite_rows = _source_rows(source, table)
            destination_rows = _destination_rows(
                destination.connection, table, columns
            )
            if len(sqlite_rows) != len(destination_rows):
                raise PilotMigrationError(
                    f"row-count mismatch for {table}: "
                    f"SQLite={len(sqlite_rows)}, PostgreSQL={len(destination_rows)}"
                )
            source_fingerprint = _fingerprint_rows(sqlite_rows, columns)
            destination_fingerprint = _fingerprint_rows(
                destination_rows, columns
            )
            if source_fingerprint != destination_fingerprint:
                raise PilotMigrationError(f"content fingerprint mismatch for {table}")
            if table in CRITICAL_TABLES:
                counts[table] = len(sqlite_rows)
                fingerprints[table] = source_fingerprint

        raw_by_source: Dict[str, int] = {}
        raw_rows = source.execute(
            """
            SELECT system.code, payload.payload_sha256, payload.payload_bytes
            FROM source_payload AS payload
            JOIN source_record_payload AS reference
              ON reference.payload_sha256 = payload.payload_sha256
            JOIN source_record AS record ON record.id = reference.source_record_id
            JOIN source_system AS system ON system.id = record.source_system_id
            ORDER BY system.code, payload.payload_sha256
            """
        ).fetchall()
        for raw in raw_rows:
            payload = bytes(raw["payload_bytes"])
            if hashlib.sha256(payload).hexdigest() != raw["payload_sha256"]:
                raise PilotMigrationError("SQLite raw payload checksum is invalid")
            destination_row = destination.connection.execute(
                """
                SELECT payload_bytes, byte_length FROM source_payload
                WHERE payload_sha256 = ?
                """,
                (raw["payload_sha256"],),
            ).fetchone()
            if destination_row is None or bytes(destination_row["payload_bytes"]) != payload:
                raise PilotMigrationError("raw payload bytes differ between databases")
            if destination_row["byte_length"] != len(payload):
                raise PilotMigrationError("raw payload length differs between databases")
            raw_by_source[raw["code"]] = raw_by_source.get(raw["code"], 0) + 1

        unsealed = destination.connection.execute(
            """
            SELECT COUNT(*) AS row_count FROM market_observation
            WHERE lifecycle_state <> 'SEALED' OR sealed_at IS NULL
            """
        ).fetchone()["row_count"]
        orphan_facts = destination.connection.execute(
            """
            SELECT (
                (SELECT COUNT(*) FROM sale_transaction f LEFT JOIN market_observation o
                  ON o.id=f.observation_id WHERE o.id IS NULL)
              + (SELECT COUNT(*) FROM listing_snapshot f LEFT JOIN market_observation o
                  ON o.id=f.observation_id WHERE o.id IS NULL)
              + (SELECT COUNT(*) FROM provider_metric_observation f LEFT JOIN market_observation o
                  ON o.id=f.observation_id WHERE o.id IS NULL)
              + (SELECT COUNT(*) FROM observation_identity_link f LEFT JOIN market_observation o
                  ON o.id=f.observation_id WHERE o.id IS NULL)
            ) AS row_count
            """
        ).fetchone()["row_count"]
        if destination.backend_name == "postgresql":
            invalid_foreign_keys = destination.connection.execute(
                """
                SELECT COUNT(*) AS row_count FROM pg_constraint
                WHERE contype = 'f' AND connamespace = current_schema()::regnamespace
                  AND NOT convalidated
                """
            ).fetchone()["row_count"]
            required_triggers = {
                "source_payload_update_guard",
                "source_record_update_guard",
                "market_observation_update_guard",
                "sale_transaction_update_guard",
                "provider_metric_observation_update_guard",
                "schema_migration_update_guard",
            }
            trigger_rows = destination.connection.execute(
                """
                SELECT trigger_name FROM information_schema.triggers
                WHERE trigger_schema = current_schema()
                """
            ).fetchall()
            active_triggers = {row["trigger_name"] for row in trigger_rows}
        else:
            invalid_foreign_keys = 0
            required_triggers = {
                "source_payload_update_guard",
                "source_record_update_guard",
                "market_observation_update_guard",
                "sale_transaction_update_guard",
                "provider_metric_update_guard",
                "schema_migration_update_guard",
            }
            active_triggers = {
                row["name"]
                for row in destination.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
        missing_triggers = sorted(required_triggers - active_triggers)
        if unsealed or orphan_facts or invalid_foreign_keys or missing_triggers:
            raise PilotMigrationError(
                "integrity verification failed: "
                f"unsealed={unsealed}, orphans={orphan_facts}, "
                f"invalid_foreign_keys={invalid_foreign_keys}, "
                f"missing_triggers={missing_triggers}"
            )
        return {
            "sqlite_sha256": sqlite_checksum(sqlite_path),
            "counts": counts,
            "fingerprints": fingerprints,
            "raw_payloads_verified": len(raw_rows),
            "raw_payloads_by_source": raw_by_source,
            "unsealed_observations": unsealed,
            "orphan_facts": orphan_facts,
            "invalid_foreign_keys": invalid_foreign_keys,
            "append_only_protections": "active",
            "sqlite_migration_versions": sorted(_sqlite_migration_catalog()),
        }
    finally:
        source.close()


def replay_retained_payloads(destination: KnowledgeBase) -> Mapping[str, Any]:
    """Re-normalize retained payloads in a transaction that always rolls back."""

    def counts() -> Dict[str, int]:
        return {
            table: destination.connection.execute(
                f"SELECT COUNT(*) AS row_count FROM {table}"
            ).fetchone()["row_count"]
            for table in TABLE_KEYS
        }

    before = counts()
    records = destination.connection.execute(
        """
        SELECT record.id, record.source_native_record_id, record.retrieved_at,
               record.source_updated_at, system.code, system.name,
               system.system_role, object.object_type,
               object.source_native_id AS external_native_id
        FROM source_record AS record
        JOIN source_system AS system ON system.id = record.source_system_id
        LEFT JOIN external_object AS object ON object.id = record.external_object_id
        WHERE system.code IN ('gcc', 'tcgdex')
        ORDER BY record.created_at, record.id
        """
    ).fetchall()
    normalizers = {"gcc": normalize_gcc, "tcgdex": normalize_tcgdex}
    diagnostics = ShadowDiagnostics()
    persistence = ShadowKnowledgePersistence(destination)
    prospective: Dict[str, int] = {}
    tcgdex_sales = 0

    class _RollbackReplay(RuntimeError):
        pass

    try:
        with destination._transaction():
            for stored in records:
                payload = destination.raw_source_payload(stored["id"])
                if not isinstance(payload, Mapping):
                    raise PilotMigrationError(
                        f"retained {stored['code']} payload is not a JSON object"
                    )
                raw = RawSourceRecord(
                    source_code=stored["code"],
                    source_name=stored["name"],
                    source_role=stored["system_role"],
                    source_native_record_id=stored["source_native_record_id"],
                    payload=payload,
                    retrieved_at=stored["retrieved_at"],
                    source_updated_at=stored["source_updated_at"],
                    object_type=stored["object_type"] or "SOURCE_RECORD",
                    external_native_id=stored["external_native_id"],
                )
                batch = normalizers[stored["code"]](raw)
                persistence.ingest(raw, batch.observations, diagnostics)

            inside = counts()
            prospective = {
                table: inside[table] - before[table]
                for table in TABLE_KEYS
                if inside[table] != before[table]
            }
            for table in (
                "source_record",
                "source_record_retrieval",
                "market_observation",
                "sale_transaction",
                "listing_snapshot",
                "provider_metric_observation",
            ):
                if inside[table] != before[table]:
                    raise PilotMigrationError(
                        f"offline replay would change durable economic table {table}"
                    )
            tcgdex_sales = destination.connection.execute(
                """
                SELECT COUNT(*) AS row_count
                FROM sale_transaction AS sale
                JOIN market_observation AS observation
                  ON observation.id = sale.observation_id
                JOIN source_system AS system
                  ON system.id = observation.source_system_id
                WHERE system.code = 'tcgdex'
                """
            ).fetchone()["row_count"]
            if tcgdex_sales:
                raise PilotMigrationError("TCGdex replay created a sale transaction")
            raise _RollbackReplay()
    except _RollbackReplay:
        pass

    after_rollback = counts()
    if after_rollback != before:
        raise PilotMigrationError("rollback-only replay changed durable state")
    return {
        "records_replayed": len(records),
        "observations_replayed": diagnostics.observations_replayed,
        "duplicate_sale_replays": diagnostics.duplicate_sale_replays,
        "economic_rows_unchanged": True,
        "prospective_non_economic_deltas": prospective,
        "transaction_rolled_back": True,
        "tcgdex_sale_transactions": tcgdex_sales,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m robot_kb.pilot_migration",
        description=(
            "Transactionally migrate/verify a read-only SQLite pilot using "
            "ROBOT_KB_DATABASE_URL. The URL is never accepted as a CLI value."
        ),
    )
    parser.add_argument("command", choices=("migrate", "replay", "verify"))
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_PILOT)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.getenv("ROBOT_KB_DATABASE_URL")
    if not database_url or not is_postgres_url(database_url):
        raise SystemExit(
            "ROBOT_KB_DATABASE_URL must contain a PostgreSQL URL in the environment"
        )
    with KnowledgeBase.open(database_url) as destination:
        result: Dict[str, Any] = {}
        if args.command == "migrate":
            result.update(migrate_sqlite_to_database(args.sqlite, destination))
        elif args.command == "replay":
            result["offline_replay"] = replay_retained_payloads(destination)
        result["verification"] = verify_sqlite_against_database(
            args.sqlite, destination
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
