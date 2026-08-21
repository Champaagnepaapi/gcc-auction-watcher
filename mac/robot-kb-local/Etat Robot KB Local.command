#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

/bin/bash "$SCRIPT_DIR/robot_kb_local_runner.sh" health

echo
for label in com.robotpokemon.kb.fixed com.robotpokemon.kb.sold com.robotpokemon.kb.backup; do
  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    echo "$label : chargé"
  else
    echo "$label : NON chargé"
  fi
done

echo
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
if [ -f "$DATA_ROOT/MIGRATION_VERIFIED" ]; then
  echo "Migration Neon vérifiée : $(cat "$DATA_ROOT/MIGRATION_VERIFIED")"
else
  echo "Migration Neon : non vérifiée"
fi
