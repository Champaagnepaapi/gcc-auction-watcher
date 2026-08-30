#!/bin/bash
set -euo pipefail

CODE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
RUNTIME_DIR="$DATA_ROOT/runtime-p3"
VENV_DIR="$DATA_ROOT/venv"
PYTHON="$VENV_DIR/bin/python"
STATE_DIR="$DATA_ROOT/state"
WORK_DIR="$DATA_ROOT/work"
LOCK_ROOT="$DATA_ROOT/locks"
LOCK_DIR="$LOCK_ROOT/cardova-sold.lock"
APP_DB_USER="robotpokemon_kb"
KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"
LOCAL_DATABASE_URL="postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb"
STATE_FILE="$STATE_DIR/cardova_paid_sold_rotation.json"
OUTPUT_FILE="$WORK_DIR/cardova_paid_sold_last.json"
COLLECTOR="$CODE_ROOT/mac/robot-kb-local/robot_kb_cardova_paid_sold_recurring.py"

mkdir -p "$STATE_DIR" "$WORK_DIR" "$LOCK_ROOT"
chmod 700 "$DATA_ROOT" "$STATE_DIR" "$WORK_DIR" "$LOCK_ROOT"

if [ ! -f "$DATA_ROOT/MIGRATION_VERIFIED" ]; then
  echo "Robot KB local: migration non vérifiée; Cardova SOLD refusé." >&2
  exit 2
fi
if [ ! -x "$PYTHON" ] || [ ! -f "$RUNTIME_DIR/robot_kb/sidecar/__main__.py" ]; then
  echo "Robot KB local: runtime P3/venv absent." >&2
  exit 2
fi
if [ ! -f "$COLLECTOR" ]; then
  echo "Robot KB local: collecteur Cardova SOLD absent." >&2
  exit 2
fi
if ! command -v security >/dev/null 2>&1; then
  echo "Robot KB local: Trousseau macOS indisponible." >&2
  exit 2
fi

PGPASSWORD="$(security find-generic-password -w -a "$APP_DB_USER" -s "$KEYCHAIN_SERVICE" 2>/dev/null || true)"
if [ -z "$PGPASSWORD" ]; then
  echo "Robot KB local: identifiant PostgreSQL absent du Trousseau." >&2
  exit 2
fi
export PGPASSWORD PGUSER="$APP_DB_USER" ROBOT_KB_DATABASE_URL="$LOCAL_DATABASE_URL"
export PYTHONPATH="$RUNTIME_DIR:$CODE_ROOT${PYTHONPATH:+:$PYTHONPATH}"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Robot KB local: lane cardova-sold déjà active (pid=$old_pid), sortie propre."
    unset PGPASSWORD PGUSER ROBOT_KB_DATABASE_URL
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo $$ > "$LOCK_DIR/pid"
cleanup() {
  rm -rf "$LOCK_DIR"
  unset PGPASSWORD PGUSER ROBOT_KB_DATABASE_URL
}
trap cleanup EXIT INT TERM

front_pages="${ROBOT_KB_CARDOVA_FRONT_PAGES:-2}"
rotation_pages="${ROBOT_KB_CARDOVA_ROTATION_PAGES:-4}"
page_size="${ROBOT_KB_CARDOVA_PAGE_SIZE:-24}"
waits=(5000 6500 8000)
status=1
attempt=0
attempt_log="$(mktemp "$WORK_DIR/cardova-sold.XXXXXX")"
trap 'rm -f "$attempt_log"; cleanup' EXIT INT TERM

for wait_ms in "${waits[@]}"; do
  attempt=$((attempt + 1))
  : > "$attempt_log"
  if "$PYTHON" "$COLLECTOR" \
      --state "$STATE_FILE" \
      --output "$OUTPUT_FILE" \
      --front-pages "$front_pages" \
      --rotation-pages "$rotation_pages" \
      --page-size "$page_size" \
      --wait-ms "$wait_ms" \
      --commit >"$attempt_log" 2>&1; then
    cat "$attempt_log"
    rm -f "$attempt_log"
    exit 0
  else
    status=$?
  fi

  cat "$attempt_log" >&2
  if ! grep -q 'TARGET_CLOSED_API_RESPONSE_NOT_OBSERVED' "$attempt_log"; then
    rm -f "$attempt_log"
    exit "$status"
  fi
  if [ "$attempt" -ge "${#waits[@]}" ]; then
    echo "Cardova SOLD: réponse publique GET non observée après ${#waits[@]} tentatives bornées." >&2
    rm -f "$attempt_log"
    exit "$status"
  fi
  echo "Cardova SOLD: GET public non observé; retry borné avec attente supérieure." >&2
done

rm -f "$attempt_log"
exit "$status"
