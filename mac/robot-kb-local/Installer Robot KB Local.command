#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
RUNTIME_DIR="$DATA_ROOT/runtime-p3"
VENV_DIR="$DATA_ROOT/venv"
LOG_DIR="$HOME/Library/Logs/RobotPokemonKB"
P3_SHA="1d06fe33b6fc640657255e15a8d17251aa02b6ce"
LOCAL_DATABASE_URL="postgresql://127.0.0.1/robot_pokemon_kb"
MIGRATION_MARKER="$DATA_ROOT/MIGRATION_VERIFIED"

mkdir -p "$DATA_ROOT" "$LOG_DIR"
chmod 700 "$DATA_ROOT" "$LOG_DIR"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew est requis. Installation officielle..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

brew list postgresql@16 >/dev/null 2>&1 || brew install postgresql@16
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew services start postgresql@16 >/dev/null
export PATH="$(brew --prefix postgresql@16)/bin:$(brew --prefix python@3.12)/bin:$PATH"

for _ in {1..30}; do
  if pg_isready -h 127.0.0.1 >/dev/null 2>&1; then break; fi
  sleep 1
done
pg_isready -h 127.0.0.1 >/dev/null

# Reuse the exact validated P3 Robot KB implementation instead of forking it.
echo "Préparation du runtime Robot KB validé ($P3_SHA)..."
git -C "$REPO_ROOT" fetch --quiet origin "$P3_SHA"
rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"
git -C "$REPO_ROOT" archive "$P3_SHA" robot_kb requirements-postgres.txt requirements.txt | tar -x -C "$RUNTIME_DIR"

PY312="$(brew --prefix python@3.12)/bin/python3.12"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PY312" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet -r "$REPO_ROOT/requirements.txt" -r "$RUNTIME_DIR/requirements-postgres.txt"

local_db_exists=false
if psql -h 127.0.0.1 -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname='robot_pokemon_kb'" | grep -q '^1$'; then
  local_db_exists=true
fi

if [ ! -f "$MIGRATION_MARKER" ]; then
  if [ "$local_db_exists" = true ]; then
    echo "Une base locale existe mais aucune migration Neon vérifiée n'est enregistrée." >&2
    echo "Collectors NON activés pour éviter de mélanger une base locale inconnue avec l'historique Neon." >&2
    exit 3
  fi
  echo
  echo "Il faut d'abord copier l'historique Neon dans le Mac avant d'activer les collectors locaux."
  printf "Lancer la migration Neon maintenant ? [O/n] "
  IFS= read -r answer
  case "${answer:-O}" in
    n|N|non|NON)
      echo "Installation préparée, mais collectors NON activés pour éviter une base parallèle vide."
      echo "Lance ensuite : Migrer Robot KB Neon vers Mac.command, puis relance cet installateur."
      exit 0
      ;;
    *) /bin/bash "$SCRIPT_DIR/Migrer Robot KB Neon vers Mac.command" ;;
  esac
fi

if [ ! -f "$MIGRATION_MARKER" ]; then
  echo "Migration Neon non vérifiée; activation locale refusée." >&2
  exit 4
fi

export ROBOT_KB_DATABASE_URL="$LOCAL_DATABASE_URL"
/bin/bash "$SCRIPT_DIR/robot_kb_local_runner.sh" health

# Generate LaunchAgents without embedding credentials. Local PostgreSQL is loopback-only.
"$VENV_DIR/bin/python" - "$SCRIPT_DIR/robot_kb_local_runner.sh" "$DATA_ROOT" "$LOG_DIR" "$HOME/Library/LaunchAgents" <<'PY'
import plistlib, sys
from pathlib import Path
runner, data_root, log_dir, agents_dir = map(Path, sys.argv[1:])
agents_dir.mkdir(parents=True, exist_ok=True)
base = {
    "ProcessType": "Background",
    "RunAtLoad": False,
    "LowPriorityIO": True,
    "EnvironmentVariables": {
        "ROBOT_KB_LOCAL_ROOT": str(data_root),
        "ROBOT_KB_DATABASE_URL": "postgresql://127.0.0.1/robot_pokemon_kb",
    },
}
def write(label, mode, schedule):
    payload = dict(base)
    payload.update({
        "Label": label,
        "ProgramArguments": ["/bin/bash", str(runner), mode],
        "StartCalendarInterval": schedule,
        "StandardOutPath": str(log_dir / f"{mode}.log"),
        "StandardErrorPath": str(log_dir / f"{mode}.err.log"),
    })
    path = agents_dir / f"{label}.plist"
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    path.chmod(0o600)
    print(path)
write("com.robotpokemon.kb.fixed", "fixed", {"Minute": 32})
write("com.robotpokemon.kb.sold", "sold", [{"Minute": 17}, {"Minute": 47}])
write("com.robotpokemon.kb.backup", "backup", {"Hour": 3, "Minute": 10})
PY

for label in com.robotpokemon.kb.fixed com.robotpokemon.kb.sold com.robotpokemon.kb.backup; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
done

# Immediate catch-up after the verified migration; GET-only collectors, no commercial action.
echo "Rattrapage local initial fixed/auction..."
/bin/bash "$SCRIPT_DIR/robot_kb_local_runner.sh" fixed
echo "Rattrapage local initial SOLD..."
/bin/bash "$SCRIPT_DIR/robot_kb_local_runner.sh" sold
/bin/bash "$SCRIPT_DIR/robot_kb_local_runner.sh" health

echo
echo "Robot KB local est actif. Neon n'est plus nécessaire pour les nouvelles écritures."
echo "Données : $DATA_ROOT"
echo "Logs : $LOG_DIR"
