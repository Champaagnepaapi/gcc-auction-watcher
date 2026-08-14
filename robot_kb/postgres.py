"""Portable PostgreSQL connection and migration support for Robot KB.

The repository deliberately uses the small DB-API surface that SQLite exposes.
``PostgresConnection`` preserves that boundary while adapting qmark
placeholders and SQLite's null-safe ``IS ?`` comparisons for psycopg.  The
driver is imported lazily so SQLite-only tests and replay need no PostgreSQL
dependency at runtime.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


POSTGRES_MIGRATION_DIRECTORY = Path(__file__).with_name("postgres_migrations")
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
_NULL_SAFE_QMARK = re.compile(r"\bIS\s+\?", re.IGNORECASE)


class PostgresConfigurationError(RuntimeError):
    """Raised for a missing driver or unsafe/unsupported database URL."""


class PostgresMigrationError(RuntimeError):
    """Raised when the PostgreSQL migration ledger is inconsistent."""


def is_postgres_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return urlsplit(value).scheme.lower() in {"postgres", "postgresql"}


def _adapt_query(query: str) -> str:
    """Adapt repository qmark SQL without changing null-safe semantics."""

    query = _NULL_SAFE_QMARK.sub("IS NOT DISTINCT FROM %s", query)
    return query.replace("?", "%s")


class PostgresConnection:
    """Minimal connection facade consumed by :class:`KnowledgeBase`."""

    backend_name = "postgresql"

    def __init__(self, raw_connection: Any, transaction_status: Any):
        self._raw = raw_connection
        self._transaction_status = transaction_status

    @property
    def in_transaction(self) -> bool:
        return self._raw.info.transaction_status != self._transaction_status.IDLE

    def execute(
        self, query: str, parameters: Optional[Sequence[Any]] = None
    ) -> Any:
        adapted = _adapt_query(query)
        if parameters is None:
            return self._raw.execute(adapted)
        return self._raw.execute(adapted, tuple(parameters))

    def executescript(self, script: str) -> None:
        # No parameters means psycopg can use PostgreSQL's simple-query path for
        # a native migration containing multiple statements.
        self._raw.execute(script, prepare=False)

    def close(self) -> None:
        self._raw.close()


def connect_postgres(database_url: str) -> PostgresConnection:
    if not is_postgres_url(database_url):
        raise PostgresConfigurationError(
            "ROBOT_KB_DATABASE_URL must use a postgres:// or postgresql:// URL"
        )
    try:
        import psycopg
        from psycopg.pq import TransactionStatus
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise PostgresConfigurationError(
            "PostgreSQL support requires psycopg; install requirements-postgres.txt"
        ) from exc

    # Explicit transactions make one sidecar ingest unit behave identically on
    # both backends and avoid a transaction leaking across source jobs.
    raw = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
    return PostgresConnection(raw, TransactionStatus)


def _migration_catalog() -> Dict[int, Tuple[Path, str]]:
    catalog: Dict[int, Tuple[Path, str]] = {}
    for path in sorted(POSTGRES_MIGRATION_DIRECTORY.glob("*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            raise PostgresMigrationError(
                f"invalid PostgreSQL migration filename: {path.name}"
            )
        version = int(match.group("version"))
        if version in catalog:
            raise PostgresMigrationError(
                f"duplicate PostgreSQL migration version: {version}"
            )
        script = path.read_text(encoding="utf-8")
        catalog[version] = (
            path,
            hashlib.sha256(script.encode("utf-8")).hexdigest(),
        )
    if not catalog:
        raise PostgresMigrationError("no PostgreSQL migrations were found")
    versions = sorted(catalog)
    if versions != list(range(1, versions[-1] + 1)):
        raise PostgresMigrationError(
            "PostgreSQL migration versions must be contiguous from 0001"
        )
    return catalog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def apply_postgres_migrations(connection: PostgresConnection) -> None:
    """Validate and apply native PostgreSQL migrations transactionally."""

    try:
        connection.execute("BEGIN")
        # Serialize first-connect schema initialization without a permanent
        # session lock; this is safe through transaction-pooling endpoints.
        connection.execute(
            "SELECT pg_advisory_xact_lock(8245917673571969890)"
        )
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
        applied: Mapping[int, Mapping[str, Any]] = {
            row["version"]: row
            for row in connection.execute(
                """
                SELECT version, filename, checksum_sha256
                FROM schema_migration ORDER BY version
                """
            ).fetchall()
        }
        catalog = _migration_catalog()
        for version, row in applied.items():
            migration = catalog.get(version)
            if migration is None:
                raise PostgresMigrationError(
                    f"applied PostgreSQL migration {version} has no repository file"
                )
            path, checksum = migration
            if row["filename"] != path.name or row["checksum_sha256"] != checksum:
                raise PostgresMigrationError(
                    f"PostgreSQL migration {version} differs from the applied migration"
                )

        for version in sorted(catalog):
            if version in applied:
                continue
            path, checksum = catalog[version]
            connection.executescript(path.read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT INTO schema_migration(
                    version, filename, checksum_sha256, applied_at
                ) VALUES (?, ?, ?, ?)
                """,
                (version, path.name, checksum, _utc_now()),
            )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
