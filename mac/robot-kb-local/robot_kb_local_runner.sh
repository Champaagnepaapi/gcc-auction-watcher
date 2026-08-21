#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
RUNTIME_DIR="$DATA_ROOT/runtime-p3"
VENV_DIR="$DATA_ROOT/venv"
STATE_DIR="$DATA_ROOT/state"
WORK_DIR="$DATA_ROOT/work"
BACKUP_DIR="$DATA_ROOT/backups/postgres"
LOG_DIR="$HOME/Library/Logs/RobotPokemonKB"
PYTHON="$VENV_DIR/bin/python"
APP_DB_USER="robotpokemon_kb"
KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"
LOCAL_DATABASE_URL="${ROBOT_KB_DATABASE_URL:-postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb}"

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
  echo "Outils PostgreSQL introuvables. Relance Installer Robot KB Local.command." >&2
  exit 2
fi
export PATH="$POSTGRES_BIN:$PATH"

if ! command -v security >/dev/null 2>&1; then
  echo "Trousseau macOS indisponible." >&2
  exit 2
fi
PGPASSWORD="$(security find-generic-password -w -a "$APP_DB_USER" -s "$KEYCHAIN_SERVICE" 2>/dev/null || true)"
if [ -z "$PGPASSWORD" ]; then
  echo "Identifiant PostgreSQL local Robot KB absent du Trousseau. Relance Installer Robot KB Local.command." >&2
  exit 2
fi
export PGPASSWORD PGUSER="$APP_DB_USER" ROBOT_KB_DATABASE_URL="$LOCAL_DATABASE_URL" ROBOT_KB_BACKUP_DIR="$BACKUP_DIR"

mkdir -p "$STATE_DIR" "$WORK_DIR" "$BACKUP_DIR" "$LOG_DIR" "$DATA_ROOT/locks"
chmod 700 "$DATA_ROOT" "$STATE_DIR" "$WORK_DIR" "$BACKUP_DIR" "$LOG_DIR" "$DATA_ROOT/locks"

if [ ! -x "$PYTHON" ] || [ ! -f "$RUNTIME_DIR/robot_kb/sidecar/__main__.py" ]; then
  echo "Robot KB local n'est pas installé. Lance d'abord Installer Robot KB Local.command." >&2
  exit 2
fi

acquire_lock() {
  LOCK_DIR="$DATA_ROOT/locks/collector.lock"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      echo "Robot KB local: un autre collector tourne déjà (pid=$old_pid), sortie propre."
      exit 0
    fi
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR"
  fi
  echo $$ > "$LOCK_DIR/pid"
  trap 'rm -rf "$LOCK_DIR"; unset PGPASSWORD' EXIT INT TERM
}

run_sidecar() {
  (cd "$RUNTIME_DIR" && "$PYTHON" -m robot_kb.sidecar "$@")
}

retry_transient_gcc() {
  local max_attempts=3
  local attempt=1
  local delay=2
  local status=0
  local attempt_log
  attempt_log="$(mktemp "$WORK_DIR/gcc-retry.XXXXXX")"

  while [ "$attempt" -le "$max_attempts" ]; do
    : > "$attempt_log"
    if "$@" >"$attempt_log" 2>&1; then
      cat "$attempt_log"
      rm -f "$attempt_log"
      return 0
    else
      status=$?
    fi

    cat "$attempt_log" >&2
    if ! grep -Eq 'HTTP (429|500|502|503|504)([^0-9]|$)|HTTP request failed' "$attempt_log"; then
      rm -f "$attempt_log"
      return "$status"
    fi

    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "GCC transient failure persisted after $max_attempts attempts." >&2
      rm -f "$attempt_log"
      return "$status"
    fi

    echo "GCC transient failure; retry $((attempt + 1))/$max_attempts in ${delay}s..." >&2
    sleep "$delay"
    delay=$((delay * 2))
    attempt=$((attempt + 1))
  done
}

run_fixed() {
  acquire_lock
  rotation_state="$STATE_DIR/v4_kb_fixed_rotation_state.json"
  target_state="$STATE_DIR/v4_kb_fixed_target_state.json"
  fixture="$WORK_DIR/v4_kb_fixed_batch.json"
  rotation_manifest="$WORK_DIR/v4_kb_fixed_rotation_manifest.json"
  hybrid_manifest="$WORK_DIR/v4_kb_fixed_hybrid_manifest.json"

  retry_transient_gcc "$PYTHON" "$REPO_ROOT/v4_kb_fixed_hybrid.py" fetch \
    --rotation-state "$rotation_state" \
    --target-state "$target_state" \
    --output-fixture "$fixture" \
    --manifest "$hybrid_manifest" \
    --rotation-manifest "$rotation_manifest" \
    --page-size 100 \
    --recent-records 100 \
    --rotation-pages 2 \
    --target-records 100

  observed_at="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["retrieved_at"])' "$hybrid_manifest")"
  run_sidecar \
    --allow-live-read-only \
    --gcc-fixture "$fixture" \
    --live-gcc auction \
    --page-size 100 \
    --max-pages 2 \
    --max-records 100 \
    --observed-at "$observed_at"

  "$PYTHON" "$REPO_ROOT/v4_kb_fixed_hybrid.py" commit \
    --rotation-state "$rotation_state" \
    --target-state "$target_state" \
    --manifest "$hybrid_manifest" \
    --rotation-manifest "$rotation_manifest"
}

run_sold() {
  acquire_lock
  sold_state="$STATE_DIR/v4_kb_sold_watermark_state.json"
  sold_fixture="$WORK_DIR/v4_kb_sold_batch.json"
  sold_manifest="$WORK_DIR/v4_kb_sold_manifest.json"
  backfill_state="$STATE_DIR/v4_kb_sold_backfill_state.json"
  backfill_fixture="$WORK_DIR/v4_kb_sold_backfill_batch.json"
  backfill_manifest="$WORK_DIR/v4_kb_sold_backfill_manifest.json"
  bootstrap_since="2026-08-15T03:00:00Z"

  retry_transient_gcc "$PYTHON" "$REPO_ROOT/v4_kb_sold_watermark.py" rotate \
    --state "$sold_state" \
    --output-fixture "$sold_fixture" \
    --manifest "$sold_manifest" \
    --bootstrap-since "$bootstrap_since" \
    --page-size 100 \
    --max-records 400 \
    --max-scan-pages 200

  observed_at="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["retrieved_at"])' "$sold_manifest")"
  run_sidecar --gcc-fixture "$sold_fixture" --observed-at "$observed_at"

  run_sidecar \
    --allow-live-read-only \
    --live-gcc sold \
    --page-size 20 \
    --max-pages 1 \
    --max-records 20

  retry_transient_gcc "$PYTHON" "$REPO_ROOT/v4_kb_sold_backfill.py" fetch \
    --state "$backfill_state" \
    --output-fixture "$backfill_fixture" \
    --manifest "$backfill_manifest" \
    --bootstrap-before "$bootstrap_since" \
    --page-size 100 \
    --max-records 400 \
    --max-page-probes 40 \
    --max-scan-pages 20

  backfill_count="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["records_count"])' "$backfill_manifest")"
  if [ "$backfill_count" -gt 0 ]; then
    backfill_observed_at="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["retrieved_at"])' "$backfill_manifest")"
    run_sidecar --gcc-fixture "$backfill_fixture" --observed-at "$backfill_observed_at"
  fi

  "$PYTHON" "$REPO_ROOT/v4_kb_sold_watermark.py" commit \
    --state "$sold_state" \
    --manifest "$sold_manifest"
  "$PYTHON" "$REPO_ROOT/v4_kb_sold_backfill.py" commit \
    --state "$backfill_state" \
    --manifest "$backfill_manifest"

  "$PYTHON" "$REPO_ROOT/robot_kb_roi_analytics.py" --output "$WORK_DIR/robot_kb_roi_snapshot.json" || true
}

run_backup() {
  acquire_lock
  (cd "$RUNTIME_DIR" && "$PYTHON" -m robot_kb.postgres_backup dump --directory "$BACKUP_DIR")
  "$PYTHON" - "$BACKUP_DIR" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
files = sorted(root.glob("robot-kb-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
for path in files[7:]:
    path.unlink()
PY
}

run_health() {
  (cd "$RUNTIME_DIR" && "$PYTHON" - <<'PY'
import json, os
from robot_kb.repository import KnowledgeBase
with KnowledgeBase.open(os.environ["ROBOT_KB_DATABASE_URL"]) as kb:
    row = kb.connection.execute("SELECT current_database() AS database_name").fetchone()
    print(json.dumps({
        "status": "OK",
        "backend": kb.backend_name,
        "database": row["database_name"],
        "schema_versions": list(kb.schema_versions()),
        "transactions": False,
    }, sort_keys=True))
PY
  )
}

case "${1:-}" in
  fixed) run_fixed ;;
  sold) run_sold ;;
  backup) run_backup ;;
  health) run_health ;;
  *)
    echo "Usage: $0 {fixed|sold|backup|health}" >&2
    exit 2
    ;;
esac
