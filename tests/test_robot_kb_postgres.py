import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot_kb import ObservationType, ResolutionState
from robot_kb.pilot_migration import (
    PilotMigrationConflict,
    TABLE_KEYS,
    migrate_sqlite_to_database,
    replay_retained_payloads,
    verify_sqlite_against_database,
)
from robot_kb.postgres import (
    _adapt_query,
    apply_postgres_migrations,
    is_postgres_url,
)
from robot_kb.postgres import POSTGRES_MIGRATION_DIRECTORY, _migration_catalog
from robot_kb.postgres_backup import (
    _command_environment,
    dump_database,
    restore_database,
)
from robot_kb.repository import KnowledgeBase


class PostgresBoundaryUnitTests(unittest.TestCase):
    def test_url_detection_is_explicit(self):
        self.assertTrue(is_postgres_url("postgresql://host/database"))
        self.assertTrue(is_postgres_url("postgres://host/database"))
        self.assertFalse(is_postgres_url("pilot.sqlite"))
        self.assertFalse(is_postgres_url("https://host/database"))

    def test_qmark_adapter_preserves_null_safe_comparison(self):
        self.assertEqual(
            _adapt_query("SELECT * FROM row WHERE a = ? AND b IS ?"),
            "SELECT * FROM row WHERE a = %s AND b IS NOT DISTINCT FROM %s",
        )

    def test_native_schema_covers_every_transfer_table_and_protection(self):
        catalog = _migration_catalog()
        self.assertEqual(list(catalog), [1, 2, 3])
        self.assertEqual(
            catalog[1][1],
            "c5357dc1dcfa99121c993c4d4567aae886990bf52ddcfb7ca93fe9266c04dffd",
        )
        script = (POSTGRES_MIGRATION_DIRECTORY / "0001_durable_shadow.sql").read_text()
        for table in TABLE_KEYS:
            self.assertIn(f"CREATE TABLE {table} (", script)
        for invariant in (
            "kb_reject_mutation",
            "kb_market_observation_update_guard",
            "kb_observation_identity_link_insert_guard",
            "kb_fx_normalization_insert_guard",
            "source_record_payload_insert_guard",
            "observation_one_cancel_or_void_meaning",
        ):
            self.assertIn(invariant, script)
        for sqlite_only in ("RAISE(ABORT", " BLOB ", " GLOB ", "BEGIN IMMEDIATE", "PRAGMA"):
            self.assertNotIn(sqlite_only, script)

    def test_forward_migration_replaces_every_trigger_alias_collision(self):
        script = (
            POSTGRES_MIGRATION_DIRECTORY / "0002_trigger_alias_safety.sql"
        ).read_text()
        for function in (
            "kb_field_resolution_insert_guard",
            "kb_market_observation_insert_guard",
            "kb_observation_relationship_insert_guard",
        ):
            self.assertIn(f"CREATE OR REPLACE FUNCTION {function}", script)
        self.assertNotRegex(script, r"(?i)\b(?:AS|JOIN)\s+(?:old|new)\b")

    def test_migration_application_handles_empty_existing_and_rerun_ledgers(self):
        catalog = _migration_catalog()

        empty = _FakePostgresMigrationConnection()
        apply_postgres_migrations(empty)
        self.assertEqual([version for version, _ in empty.scripts], [1, 2, 3])
        self.assertEqual(sorted(empty.applied), [1, 2, 3])
        apply_postgres_migrations(empty)
        self.assertEqual([version for version, _ in empty.scripts], [1, 2, 3])

        version_1_path, version_1_checksum = catalog[1]
        existing = _FakePostgresMigrationConnection(
            {
                1: {
                    "version": 1,
                    "filename": version_1_path.name,
                    "checksum_sha256": version_1_checksum,
                }
            }
        )
        apply_postgres_migrations(existing)
        self.assertEqual([version for version, _ in existing.scripts], [2, 3])
        self.assertEqual(sorted(existing.applied), [1, 2, 3])
        apply_postgres_migrations(existing)
        self.assertEqual([version for version, _ in existing.scripts], [2, 3])

    def test_backup_environment_keeps_password_out_of_database_name(self):
        url = (
            "postgresql://robot:secret@example.test:5432/pilot"
            "?sslmode=require&channel_binding=require"
        )
        environment = _command_environment(url)
        self.assertEqual(environment["PGDATABASE"], "pilot")
        self.assertEqual(environment["PGPASSWORD"], "secret")
        self.assertEqual(environment["PGSSLMODE"], "require")
        self.assertNotIn(url, environment.values())

    def test_backup_uses_custom_format_and_atomic_destination(self):
        with tempfile.TemporaryDirectory() as root:
            commands = []

            def fake_run(command, database_url):
                commands.append((tuple(command), database_url))
                output = Path(command[command.index("--file") + 1])
                output.write_bytes(b"custom archive")

            with mock.patch(
                "robot_kb.postgres_backup._require_tool",
                return_value="/usr/bin/pg_dump",
            ), mock.patch("robot_kb.postgres_backup._run", side_effect=fake_run):
                backup = dump_database(
                    "postgresql://robot:secret@example.test/pilot", Path(root)
                )
            self.assertTrue(backup.exists())
            self.assertIn("--format=custom", commands[0][0])
            self.assertNotIn("secret", " ".join(commands[0][0]))
            self.assertFalse(backup.with_suffix(".dump.tmp").exists())

    def test_restore_keeps_password_out_of_command(self):
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / "pilot.dump"
            archive.write_bytes(b"custom archive")
            commands = []
            with mock.patch(
                "robot_kb.postgres_backup._require_tool",
                return_value="/usr/bin/pg_restore",
            ), mock.patch(
                "robot_kb.postgres_backup._run",
                side_effect=lambda command, url: commands.append(tuple(command)),
            ):
                restore_database(
                    archive,
                    "postgresql://robot:secret@example.test/pilot_restore",
                )
            rendered = " ".join(commands[0])
            self.assertIn("pilot_restore", rendered)
            self.assertNotIn("secret", rendered)
            self.assertNotIn("postgresql://", rendered)


class SQLitePilotTransferContractTests(unittest.TestCase):
    def _source(self, path: Path) -> tuple[str, str]:
        with KnowledgeBase.open(path) as source:
            source_id = source.create_source_system("gcc", "GCC", "PROVIDER")
            record_id = source.append_source_record(
                source_id,
                "listing-1",
                b"\x00pilot raw bytes\xff",
                retrieved_at="2026-08-14T08:00:00Z",
            )
        return source_id, record_id

    def test_import_raw_round_trip_rerun_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = Path(root) / "source.sqlite"
            destination_path = Path(root) / "destination.sqlite"
            _, record_id = self._source(source_path)
            with KnowledgeBase.open(destination_path) as destination:
                first = migrate_sqlite_to_database(
                    source_path, destination, require_postgres=False
                )
                second = migrate_sqlite_to_database(
                    source_path, destination, require_postgres=False
                )
                verification = verify_sqlite_against_database(
                    source_path, destination
                )
                self.assertGreater(first["rows_inserted"], 0)
                self.assertEqual(second["rows_inserted"], 0)
                self.assertEqual(
                    destination.raw_source_payload(record_id),
                    b"\x00pilot raw bytes\xff",
                )
                self.assertEqual(verification["raw_payloads_verified"], 1)
                self.assertEqual(verification["counts"]["sale_transaction"], 0)

    def test_conflicting_existing_key_fails_loudly(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = Path(root) / "source.sqlite"
            destination_path = Path(root) / "destination.sqlite"
            source_id, _ = self._source(source_path)
            with KnowledgeBase.open(destination_path) as destination:
                destination.connection.execute(
                    """
                    INSERT INTO source_system(id, code, name, system_role, created_at)
                    VALUES (?, 'different', 'Different', 'PROVIDER', ?)
                    """,
                    (source_id, "2026-08-14T08:00:00Z"),
                )
                with self.assertRaises(PilotMigrationConflict):
                    migrate_sqlite_to_database(
                        source_path, destination, require_postgres=False
                    )

    def test_conflict_rolls_back_rows_inserted_earlier_in_unit(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = Path(root) / "source.sqlite"
            destination_path = Path(root) / "destination.sqlite"
            with KnowledgeBase.open(source_path) as source:
                first_id = source.create_source_system("a", "A", "PROVIDER")
                second_id = source.create_source_system("b", "B", "PROVIDER")
            with KnowledgeBase.open(destination_path) as destination:
                destination.connection.execute(
                    """
                    INSERT INTO source_system(id, code, name, system_role, created_at)
                    VALUES (?, 'conflict', 'Conflict', 'PROVIDER', ?)
                    """,
                    (second_id, "2026-08-14T08:00:00Z"),
                )
                with self.assertRaises(PilotMigrationConflict):
                    migrate_sqlite_to_database(
                        source_path, destination, require_postgres=False
                    )
                self.assertIsNone(
                    destination.connection.execute(
                        "SELECT id FROM source_system WHERE id = ?", (first_id,)
                    ).fetchone()
                )

    def test_source_connection_is_query_only(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = Path(root) / "source.sqlite"
            self._source(source_path)
            original = source_path.read_bytes()
            with KnowledgeBase.open(Path(root) / "destination.sqlite") as destination:
                migrate_sqlite_to_database(
                    source_path, destination, require_postgres=False
                )
            self.assertEqual(source_path.read_bytes(), original)

    def test_offline_replay_is_always_rolled_back(self):
        with tempfile.TemporaryDirectory() as root:
            source_path = Path(root) / "source.sqlite"
            destination_path = Path(root) / "destination.sqlite"
            with KnowledgeBase.open(source_path) as source:
                source_id = source.create_source_system(
                    "tcgdex", "TCGdex", "PROVIDER"
                )
                external_object_id = source.create_external_object(
                    source_id, "CARD", "card-1"
                )
                source.append_source_record(
                    source_id,
                    "card-1",
                    {"id": "card-1", "name": "Replay card"},
                    retrieved_at="2026-08-14T08:00:00Z",
                    external_object_id=external_object_id,
                )
            with KnowledgeBase.open(destination_path) as destination:
                migrate_sqlite_to_database(
                    source_path, destination, require_postgres=False
                )
                result = replay_retained_payloads(destination)
                self.assertTrue(result["transaction_rolled_back"])
                verify_sqlite_against_database(source_path, destination)


@unittest.skipUnless(
    os.getenv("ROBOT_KB_TEST_DATABASE_URL"),
    "ROBOT_KB_TEST_DATABASE_URL is not configured for ephemeral PostgreSQL tests",
)
class PostgresIntegrationTests(unittest.TestCase):
    """Non-destructive integration checks for a dedicated disposable database."""

    def setUp(self):
        self.kb = KnowledgeBase.open(os.environ["ROBOT_KB_TEST_DATABASE_URL"])
        self.kb.connection.execute("BEGIN")

    def tearDown(self):
        if self.kb.connection.in_transaction:
            self.kb.connection.execute("ROLLBACK")
        self.kb.close()

    def test_empty_schema_migration_and_raw_payload_round_trip(self):
        self.assertEqual(self.kb.schema_versions(), [1, 2])
        source_id = self.kb.create_source_system(
            "pg-test-" + os.urandom(8).hex(), "PG test", "PROVIDER"
        )
        record_id = self.kb.append_source_record(
            source_id,
            "record-" + os.urandom(8).hex(),
            b"postgres raw \x00 bytes",
            retrieved_at="2026-08-14T08:00:00Z",
        )
        self.assertEqual(self.kb.raw_source_payload(record_id), b"postgres raw \x00 bytes")

    def test_append_only_protection(self):
        source_id = self.kb.create_source_system(
            "pg-immutable-" + os.urandom(8).hex(), "PG immutable", "PROVIDER"
        )
        with self.assertRaises(Exception):
            self.kb.connection.execute(
                "UPDATE source_system SET name = 'changed' WHERE id = ?", (source_id,)
            )

    def test_transaction_rollback(self):
        code = "pg-rollback-" + os.urandom(8).hex()
        with self.assertRaises(RuntimeError):
            with self.kb._transaction():
                self.kb.create_source_system(code, "rollback", "PROVIDER")
                raise RuntimeError("injected")
        self.assertIsNone(
            self.kb.connection.execute(
                "SELECT id FROM source_system WHERE code = ?", (code,)
            ).fetchone()
        )

    def test_0001_and_0002_apply_from_empty_schema_transactionally(self):
        schema = "kb_pgtest_" + os.urandom(8).hex()
        with self.assertRaises(_RollbackFixture):
            with self.kb._transaction():
                self.kb.connection.execute(f'CREATE SCHEMA "{schema}"')
                self.kb.connection.execute(
                    f'SET LOCAL search_path TO "{schema}"'
                )
                self.kb.connection.execute(
                    """
                    CREATE TABLE schema_migration (
                        version INTEGER PRIMARY KEY,
                        filename TEXT NOT NULL UNIQUE,
                        checksum_sha256 TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                for version, (path, checksum) in _migration_catalog().items():
                    self.kb.connection.executescript(path.read_text(encoding="utf-8"))
                    self.kb.connection.execute(
                        """
                        INSERT INTO schema_migration(
                            version, filename, checksum_sha256, applied_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (version, path.name, checksum, "2026-08-14T00:00:00Z"),
                    )
                self.assertEqual(self.kb.schema_versions(), [1, 2])
                functions = self.kb.connection.execute(
                    """
                    SELECT p.proname
                    FROM pg_proc AS p
                    JOIN pg_namespace AS n ON n.oid = p.pronamespace
                    WHERE n.nspname = ? AND p.proname IN (
                        'kb_field_resolution_insert_guard',
                        'kb_market_observation_insert_guard',
                        'kb_observation_relationship_insert_guard'
                    )
                    """,
                    (schema,),
                ).fetchall()
                self.assertEqual(len(functions), 3)
                raise _RollbackFixture()

    def test_trigger_alias_remediation_paths_and_rejections(self):
        suffix = os.urandom(8).hex()
        source_id = self.kb.create_source_system(
            "pg-alias-" + suffix, "PG alias test", "PROVIDER"
        )
        record_id = self.kb.append_source_record(
            source_id,
            "record-" + suffix,
            {"fixture": suffix},
            retrieved_at="2026-08-14T08:00:00Z",
        )
        subject_a = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=record_id
        )
        subject_b = self.kb.create_identity_subject(
            "PROVIDER_RESPONSE", source_record_id=record_id
        )
        first_resolution = self.kb.resolve_field(
            subject_a, "finish", ResolutionState.UNKNOWN
        )
        second_resolution = self.kb.resolve_field(
            subject_a,
            "finish",
            ResolutionState.UNKNOWN,
            supersedes_resolution_id=first_resolution,
        )
        self.assertIsNotNone(second_resolution)

        with self.assertRaises(Exception):
            with self.kb._transaction():
                self.kb.connection.execute(
                    """
                    INSERT INTO field_resolution(
                        id, identity_subject_id, field_name, resolution_state,
                        supersedes_resolution_id, created_at
                    ) VALUES (?, ?, 'finish', 'UNKNOWN', ?, ?)
                    """,
                    (
                        "fres_" + os.urandom(16).hex(),
                        subject_b,
                        first_resolution,
                        "2026-08-14T08:00:00Z",
                    ),
                )

        first_observation = self.kb.append_market_observation(
            ObservationType.LISTING_SNAPSHOT,
            source_id,
            "listing-" + suffix,
            observed_at="2026-08-14T08:00:00Z",
            fact={"snapshot_status": "ACTIVE"},
        )
        second_observation = self.kb.append_market_observation(
            ObservationType.LISTING_SNAPSHOT,
            source_id,
            "listing-" + suffix,
            observed_at="2026-08-14T09:00:00Z",
            revision_of_observation_id=first_observation,
            fact={"snapshot_status": "ENDED"},
        )
        relation = self.kb.connection.execute(
            """
            SELECT relationship_type FROM observation_relationship
            WHERE from_observation_id = ? AND to_observation_id = ?
            """,
            (second_observation, first_observation),
        ).fetchone()
        self.assertEqual(relation["relationship_type"], "REVISION_OF")

        with self.assertRaises(Exception):
            with self.kb._transaction():
                self.kb.connection.execute(
                    """
                    INSERT INTO market_observation(
                        id, observation_type, source_system_id,
                        source_native_record_id, idempotency_key,
                        content_sha256, event_time_precision, observed_at,
                        ingested_at, revision_of_observation_id, created_at
                    ) VALUES (?, 'LISTING_SNAPSHOT', ?, ?, ?, ?, 'UNKNOWN', ?, ?, ?, ?)
                    """,
                    (
                        "observation_" + os.urandom(16).hex(),
                        source_id,
                        "incompatible-" + suffix,
                        "obskey_" + os.urandom(16).hex(),
                        os.urandom(32).hex(),
                        "2026-08-14T10:00:00Z",
                        "2026-08-14T10:00:00Z",
                        first_observation,
                        "2026-08-14T10:00:00Z",
                    ),
                )

        with self.assertRaises(Exception):
            with self.kb._transaction():
                self.kb.connection.execute(
                    """
                    INSERT INTO observation_relationship(
                        id, from_observation_id, to_observation_id,
                        relationship_type, created_at
                    ) VALUES (?, ?, ?, 'REVISION_OF', ?)
                    """,
                    (
                        "orel_" + os.urandom(16).hex(),
                        first_observation,
                        second_observation,
                        "2026-08-14T10:00:00Z",
                    ),
                )


class _RollbackFixture(RuntimeError):
    pass


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows


class _FakePostgresMigrationConnection:
    def __init__(self, applied=None):
        self.applied = dict(applied or {})
        self.scripts = []
        self.in_transaction = False

    def execute(self, query, parameters=None):
        normalized = " ".join(query.split())
        if normalized == "BEGIN":
            self.in_transaction = True
        elif normalized == "COMMIT":
            self.in_transaction = False
        elif normalized == "ROLLBACK":
            self.in_transaction = False
        elif normalized.startswith(
            "SELECT version, filename, checksum_sha256 FROM schema_migration"
        ):
            return _Rows(self.applied[version] for version in sorted(self.applied))
        elif normalized.startswith("INSERT INTO schema_migration"):
            version, filename, checksum, _ = parameters
            self.applied[version] = {
                "version": version,
                "filename": filename,
                "checksum_sha256": checksum,
            }
        return _Rows()

    def executescript(self, script):
        for version, (path, _) in _migration_catalog().items():
            if path.read_text(encoding="utf-8") == script:
                self.scripts.append((version, script))
                return
        raise AssertionError("migration script is not in the repository catalog")


if __name__ == "__main__":
    unittest.main()
