"""Small deterministic SQLite migration runner."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Iterator, Union


MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
MIGRATION_DIRECTORY = Path(__file__).with_name("migrations")


class MigrationError(RuntimeError):
    pass


def connect_database(path: Union[str, Path] = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise MigrationError("SQLite foreign key enforcement is unavailable")
    return connection


def _sql_statements(script: str) -> Iterator[str]:
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                yield statement
    if buffer.strip():
        raise MigrationError("incomplete SQL statement in migration")


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        row["version"]: row
        for row in connection.execute(
            "SELECT version, filename, checksum_sha256 FROM schema_migration"
        )
    }

    migration_files = sorted(MIGRATION_DIRECTORY.glob("*.sql"))
    if not migration_files:
        raise MigrationError("no knowledge-base migrations were found")

    for path in migration_files:
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"invalid migration filename: {path.name}")
        version = int(match.group("version"))
        script = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
        existing = applied.get(version)
        if existing is not None:
            if (
                existing["filename"] != path.name
                or existing["checksum_sha256"] != checksum
            ):
                raise MigrationError(
                    f"migration {version} differs from the applied migration"
                )
            continue

        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _sql_statements(script):
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migration(
                    version, filename, checksum_sha256, applied_at
                ) VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (version, path.name, checksum),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
