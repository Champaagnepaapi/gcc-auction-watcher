import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot_kb.pilot_migration import (
    PilotMigrationConflict,
    TABLE_KEYS,
    migrate_sqlite_to_database,
    replay_retained_payloads,
    verify_sqlite_against_database,
)
from robot_kb.postgres import _adapt_query, is_postgres_url
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
        self.assertEqual(list(catalog), [1])
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

    def tearDown(self):
        self.kb.close()

    def test_empty_schema_migration_and_raw_payload_round_trip(self):
        self.assertEqual(self.kb.schema_versions(), [1])
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


if __name__ == "__main__":
    unittest.main()
