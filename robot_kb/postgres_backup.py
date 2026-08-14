"""Secret-safe pg_dump/pg_restore tooling for the durable Robot KB."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qsl, unquote, urlsplit

from .pilot_migration import TABLE_KEYS, _fingerprint_rows
from .postgres import is_postgres_url
from .repository import KnowledgeBase


DEFAULT_BACKUP_DIRECTORY = (
    Path.home() / "robot-pokemon-data" / "backups" / "postgres"
)


class BackupError(RuntimeError):
    pass


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise BackupError(f"{name} is required but is not installed")
    return path


def _command_environment(database_url: str) -> Mapping[str, str]:
    if not is_postgres_url(database_url):
        raise BackupError("database environment variable is not a PostgreSQL URL")
    parts = urlsplit(database_url)
    if not parts.hostname or not parts.path.lstrip("/"):
        raise BackupError("PostgreSQL URL must include a host and database")
    environment = dict(os.environ)
    # Split the URI into libpq environment fields so neither the URL nor its
    # password appears in argv, process listings, command traces, or logs.
    environment["PGHOST"] = parts.hostname
    environment["PGDATABASE"] = unquote(parts.path.lstrip("/"))
    if parts.port is not None:
        environment["PGPORT"] = str(parts.port)
    if parts.username is not None:
        environment["PGUSER"] = unquote(parts.username)
    if parts.password is not None:
        environment["PGPASSWORD"] = unquote(parts.password)
    query_environment = {
        "sslmode": "PGSSLMODE",
        "channel_binding": "PGCHANNELBINDING",
        "application_name": "PGAPPNAME",
        "options": "PGOPTIONS",
        "sslrootcert": "PGSSLROOTCERT",
    }
    for name, value in parse_qsl(parts.query, keep_blank_values=False):
        variable = query_environment.get(name)
        if variable is not None:
            environment[variable] = value
    environment.pop("ROBOT_KB_DATABASE_URL", None)
    environment.pop("ROBOT_KB_RESTORE_DATABASE_URL", None)
    return environment


def _run(command: Sequence[str], database_url: str) -> None:
    completed = subprocess.run(
        list(command),
        env=_command_environment(database_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if completed.returncode:
        # pg tools can echo connection details in diagnostics.  Return a useful
        # status without reflecting captured output or credentials.
        raise BackupError(
            f"{Path(command[0]).name} failed with exit status {completed.returncode}"
        )


def dump_database(database_url: str, backup_directory: Path) -> Path:
    pg_dump = _require_tool("pg_dump")
    directory = backup_directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"robot-kb-{timestamp}.dump"
    temporary = destination.with_suffix(".dump.tmp")
    if destination.exists() or temporary.exists():
        raise BackupError("refusing to overwrite an existing backup path")
    try:
        _run(
            (
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(temporary),
            ),
            database_url,
        )
        temporary.chmod(0o600)
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return destination


def restore_database(backup: Path, database_url: str) -> None:
    pg_restore = _require_tool("pg_restore")
    source = backup.expanduser().resolve(strict=True)
    database_name = unquote(urlsplit(database_url).path.lstrip("/"))
    if not database_name:
        raise BackupError("PostgreSQL URL must include a database")
    _run(
        (
            pg_restore,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            database_name,
            str(source),
        ),
        database_url,
    )


def _postgres_columns(knowledge_base: KnowledgeBase, table: str) -> Sequence[str]:
    rows = knowledge_base.connection.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = ?
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    columns = [row["column_name"] for row in rows]
    if not columns:
        raise BackupError(f"restored database is missing table {table}")
    return columns


def _database_fingerprints(database_url: str) -> Mapping[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    with KnowledgeBase.open(database_url) as knowledge_base:
        for table, keys in TABLE_KEYS.items():
            columns = _postgres_columns(knowledge_base, table)
            rows = knowledge_base.connection.execute(
                f"SELECT {', '.join(columns)} FROM {table} "
                f"ORDER BY {', '.join(keys)}"
            ).fetchall()
            result[table] = {
                "rows": len(rows),
                "sha256": _fingerprint_rows(rows, columns),
            }
    return result


def restore_and_verify(
    backup: Path, source_database_url: str, restore_database_url: str
) -> Mapping[str, Mapping[str, Any]]:
    if source_database_url == restore_database_url:
        raise BackupError("restore verification database must differ from the source")
    restore_database(backup, restore_database_url)
    source = _database_fingerprints(source_database_url)
    restored = _database_fingerprints(restore_database_url)
    if source != restored:
        raise BackupError("restored database counts or fingerprints differ")
    return source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m robot_kb.postgres_backup",
        description=(
            "Create or verify custom-format PostgreSQL backups. Database URLs "
            "are read only from environment variables and never printed."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    dump = subparsers.add_parser("dump")
    dump.add_argument(
        "--directory",
        type=Path,
        default=Path(
            os.getenv("ROBOT_KB_BACKUP_DIR", str(DEFAULT_BACKUP_DIRECTORY))
        ),
    )
    verify = subparsers.add_parser("restore-verify")
    verify.add_argument("backup", type=Path)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    database_url = os.getenv("ROBOT_KB_DATABASE_URL")
    if not database_url:
        raise SystemExit("ROBOT_KB_DATABASE_URL is required")
    if args.command == "dump":
        backup = dump_database(database_url, args.directory)
        print(json.dumps({"backup": str(backup)}, sort_keys=True))
        return 0
    restore_url = os.getenv("ROBOT_KB_RESTORE_DATABASE_URL")
    if not restore_url:
        raise SystemExit("ROBOT_KB_RESTORE_DATABASE_URL is required")
    fingerprints = restore_and_verify(args.backup, database_url, restore_url)
    print(json.dumps({"verified": fingerprints}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
