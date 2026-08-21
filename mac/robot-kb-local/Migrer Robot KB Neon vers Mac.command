#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
RUNTIME_DIR="$DATA_ROOT/runtime-p3"
VENV_DIR="$DATA_ROOT/venv"
MIGRATION_DIR="$DATA_ROOT/migration-backup"
PYTHON="$VENV_DIR/bin/python"
LOCAL_DATABASE_URL="postgresql://127.0.0.1/robot_pokemon_kb"
export PATH="/opt/homebrew/opt/postgresql@16/bin:/usr/local/opt/postgresql@16/bin:$PATH"

if [ ! -x "$PYTHON" ] || [ ! -f "$RUNTIME_DIR/robot_kb/postgres_backup.py" ]; then
  echo "Lance d'abord Installer Robot KB Local.command." >&2
  exit 2
fi

if ! command -v pg_dump >/dev/null || ! command -v pg_restore >/dev/null; then
  echo "Les outils PostgreSQL locaux sont absents." >&2
  exit 2
fi

if psql -h 127.0.0.1 -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname='robot_pokemon_kb'" | grep -q '^1$'; then
  echo "La base locale robot_pokemon_kb existe déjà. Migration refusée pour ne pas écraser des données." >&2
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
  unset NEON_URL ROBOT_KB_DATABASE_URL ROBOT_KB_SOURCE_URL ROBOT_KB_RESTORE_DATABASE_URL
}
trap cleanup_secret EXIT INT TERM

# Dump through the proven secret-safe helper: credentials are split into libpq
# environment variables and never passed in argv or printed.
export ROBOT_KB_DATABASE_URL="$NEON_URL"
export ROBOT_KB_BACKUP_DIR="$MIGRATION_DIR"
echo "Export Neon en cours..."
dump_json="$(cd "$RUNTIME_DIR" && "$PYTHON" -m robot_kb.postgres_backup dump --directory "$MIGRATION_DIR")"
dump_path="$($PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["backup"])' "$dump_json")"
unset ROBOT_KB_DATABASE_URL

createdb -h 127.0.0.1 robot_pokemon_kb
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
  echo "Restore local échoué. La base locale créée pour cette tentative va être supprimée; le dump Neon est conservé." >&2
  dropdb -h 127.0.0.1 robot_pokemon_kb || true
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
