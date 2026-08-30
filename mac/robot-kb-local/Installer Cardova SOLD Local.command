#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
CODE_SHA="a2f1878186a8850d5a4c4763518a10ecfd16f2fc"
CODE_DIR="$DATA_ROOT/cardova-sold-code"
TEMP_DIR="$DATA_ROOT/.cardova-sold-code.new.$$"
LOG_DIR="$HOME/Library/Logs/RobotPokemonKB"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LABEL="com.robotpokemon.kb.cardova-sold"
PLIST="$AGENTS_DIR/$LABEL.plist"
MARKER="$DATA_ROOT/CARDOVA_SOLD_RUNTIME_SHA"

mkdir -p "$DATA_ROOT" "$LOG_DIR" "$AGENTS_DIR"
chmod 700 "$DATA_ROOT" "$LOG_DIR"

if [ ! -f "$DATA_ROOT/MIGRATION_VERIFIED" ]; then
  echo "Migration Robot KB locale non vérifiée; installation Cardova SOLD refusée." >&2
  exit 2
fi
if [ ! -x "$DATA_ROOT/venv/bin/python" ] || [ ! -f "$DATA_ROOT/runtime-p3/robot_kb/sidecar/__main__.py" ]; then
  echo "Robot KB local P3 n'est pas installé." >&2
  exit 2
fi

# Install an immutable repository snapshot instead of pointing LaunchAgent at a
# temporary worktree. No credential is copied into this snapshot.
git -C "$REPO_ROOT" fetch --quiet origin "$CODE_SHA"
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
git -C "$REPO_ROOT" archive "$CODE_SHA" | tar -x -C "$TEMP_DIR"
if [ ! -f "$TEMP_DIR/mac/robot-kb-local/robot_kb_cardova_paid_sold_runner.sh" ] || \
   [ ! -f "$TEMP_DIR/mac/robot-kb-local/robot_kb_cardova_paid_sold_recurring.py" ]; then
  rm -rf "$TEMP_DIR"
  echo "Snapshot Cardova SOLD incomplet; installation refusée." >&2
  exit 3
fi
rm -rf "$CODE_DIR"
mv "$TEMP_DIR" "$CODE_DIR"
printf '%s\n' "$CODE_SHA" > "$MARKER"
chmod 600 "$MARKER"

python3 - "$CODE_DIR/mac/robot-kb-local/robot_kb_cardova_paid_sold_runner.sh" "$DATA_ROOT" "$LOG_DIR" "$PLIST" <<'PY'
import plistlib
from pathlib import Path
import sys

runner = Path(sys.argv[1])
data_root = Path(sys.argv[2])
log_dir = Path(sys.argv[3])
plist = Path(sys.argv[4])
payload = {
    "Label": "com.robotpokemon.kb.cardova-sold",
    "ProcessType": "Background",
    "RunAtLoad": False,
    "LowPriorityIO": True,
    "ProgramArguments": ["/bin/bash", str(runner)],
    "EnvironmentVariables": {
        "ROBOT_KB_LOCAL_ROOT": str(data_root),
    },
    # Four bounded cycles/day, offset from GCC/multisource lanes.
    "StartCalendarInterval": [
        {"Hour": 2, "Minute": 23},
        {"Hour": 8, "Minute": 23},
        {"Hour": 14, "Minute": 23},
        {"Hour": 20, "Minute": 23},
    ],
    "StandardOutPath": str(log_dir / "cardova-sold.log"),
    "StandardErrorPath": str(log_dir / "cardova-sold.err.log"),
}
with plist.open("wb") as handle:
    plistlib.dump(payload, handle, sort_keys=True)
plist.chmod(0o600)
PY

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

if ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "LaunchAgent Cardova SOLD non chargé." >&2
  exit 4
fi

echo "Cardova SOLD local installé : $LABEL"
echo "Runtime pin : $CODE_SHA"
echo "Cadence : 02:23 / 08:23 / 14:23 / 20:23"
echo "State : $DATA_ROOT/state/cardova_paid_sold_rotation.json"
echo "Aucun secret dans le plist; PostgreSQL est lu depuis le Trousseau au runtime."
