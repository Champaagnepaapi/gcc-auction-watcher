#!/bin/bash
set -euo pipefail

DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
RUNTIME_DIR="$DATA_ROOT/runtime-p3"
VENV_DIR="$DATA_ROOT/venv"
MIGRATION_DIR="$DATA_ROOT/migration-backup"
PYTHON="$VENV_DIR/bin/python"
APP_DB_USER="robotpokemon_kb"
KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"
LOCAL_DATABASE_URL="postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb"

find_postgres_bin() {
  local candidate
  if command -v psql >/dev/null 2>&1 && command -v pg_dump >/dev/null 2>&1; then
    dirname "$(command -v psql)"
    return 0
  fi
  for candidate in \
    /Library/PostgreSQL/18/bin \
    /Library/PostgreSQL/17/bin \
    /Library/PostgreSQL/16/bin \
    /opt/homebrew/opt/postgresql@18/bin \
    /opt/homebrew/opt/postgresql@17/bin \
    /opt/homebrew/opt/postgresql@16/bin \
    /usr/local/opt/postgresql@18/bin \
    /usr/local/opt/postgresql@17/bin \
    /usr/local/opt/postgresql@16/bin; do
    if [ -x "$candidate/psql" ] && [ -x "$candidate/pg_dump" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

POSTGRES_BIN="$(find_postgres_bin || true)"
if [ -z "$POSTGRES_BIN" ]; then
  echo "Les outils PostgreSQL locaux sont absents." >&2
  exit 2
fi
export PATH="$POSTGRES_BIN:$PATH"

if [ ! -x "$PYTHON" ] || [ ! -f "$RUNTIME_DIR/robot_kb/postgres_backup.py" ]; then
  echo "Lance d'abord Installer Robot KB Local.command." >&2
  exit 2
fi

PGPASSWORD="$(security find-generic-password -w -a "$APP_DB_USER" -s "$KEYCHAIN_SERVICE" 2>/dev/null || true)"
if [ -z "$PGPASSWORD" ]; then
  echo "Identifiant PostgreSQL local Robot KB absent du Trousseau. Relance Installer Robot KB Local.command." >&2
  exit 2
fi
export PGPASSWORD PGUSER="$APP_DB_USER"

if ! psql "$LOCAL_DATABASE_URL" -Atqc 'SELECT 1' >/dev/null 2>&1; then
  echo "La base locale robot_pokemon_kb n'est pas accessible." >&2
  exit 2
fi

local_table_count="$(psql "$LOCAL_DATABASE_URL" -Atqc "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")"
if [ "${local_table_count:-0}" -gt 0 ]; then
  echo "La base locale robot_pokemon_kb contient déjà des tables. Migration refusée pour ne pas écraser des données." >&2
  echo "Si c'est une installation déjà migrée, utilise Etat Robot KB Local.command." >&2
  exit 3
fi

printf "Colle la DATABASE URL Neon de robot-pokemon-kb (entrée masquée), puis Entrée : "
IFS= read -r -s NEON_URL
printf "\n"
case "$NEON_URL" in
  postgres://*|postgresql://*) ;;
  *) echo "URL PostgreSQL invalide." >&2; exit 2 ;;
esac

mkdir -p "$MIGRATION_DIR"
chmod 700 "$MIGRATION_DIR"

cleanup_secret() {
  unset NEON_URL ROBOT_KB_DATABASE_URL ROBOT_KB_SOURCE_URL ROBOT_KB_RESTORE_DATABASE_URL PGPASSWORD
}
trap cleanup_secret EXIT INT TERM

# Dump through the proven secret-safe helper: credentials are split into libpq
# environment variables and never passed in argv or printed.
export ROBOT_KB_DATABASE_URL="$NEON_URL"
export ROBOT_KB_BACKUP_DIR="$MIGRATION_DIR"
echo "Export Neon en cours..."
dump_json="$(cd "$RUNTIME_DIR" && "$PYTHON" -m robot_kb.postgres_backup dump --directory "$MIGRATION_DIR")"
dump_path="$("$PYTHON" -c 'import json,sys; print(json.loads(sys.argv[1])["backup"])' "$dump_json")"
unset ROBOT_KB_DATABASE_URL

restore_failed=0
export ROBOT_KB_DATABASE_URL="$LOCAL_DATABASE_URL"
if ! (cd "$RUNTIME_DIR" && "$PYTHON" - "$dump_path" <<'PY'
import os, sys
from pathlib import Path
from robot_kb.postgres_backup import restore_database
restore_database(Path(sys.argv[1]), os.environ["ROBOT_KB_DATABASE_URL"])
PY
); then
  restore_failed=1
fi

if [ "$restore_failed" -ne 0 ]; then
  echo "Restore local échoué. Nettoyage de la base locale de cette tentative; le dump Neon est conservé." >&2
  psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null || true
DROP SCHEMA public CASCADE;
CREATE SCHEMA public AUTHORIZATION robotpokemon_kb;
SQL
  exit 4
fi

# Exact table counts + fingerprints against the source. No connection string is printed.
export ROBOT_KB_SOURCE_URL="$NEON_URL"
export ROBOT_KB_DATABASE_URL="$LOCAL_DATABASE_URL"
echo "Vérification source ↔ Mac..."
(cd "$RUNTIME_DIR" && "$PYTHON" - <<'PY'
import json, os
from robot_kb.postgres_backup import _database_fingerprints
source = _database_fingerprints(os.environ["ROBOT_KB_SOURCE_URL"])
local = _database_fingerprints(os.environ["ROBOT_KB_DATABASE_URL"])
if source != local:
    raise SystemExit("MIGRATION_VERIFY_MISMATCH")
print(json.dumps({
    "verified": True,
    "tables": len(local),
    "rows": sum(int(v["rows"]) for v in local.values()),
}, sort_keys=True))
PY
)

printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DATA_ROOT/MIGRATION_VERIFIED"
chmod 600 "$DATA_ROOT/MIGRATION_VERIFIED"
echo "Migration Neon -> PostgreSQL local vérifiée. Le dump source est conservé dans : $MIGRATION_DIR"
