#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
PYTHON="$DATA_ROOT/venv/bin/python"
MIGRATION_MARKER="$DATA_ROOT/MIGRATION_VERIFIED"
APP_DB_USER="robotpokemon_kb"
KEYCHAIN_SERVICE="RobotPokemonKB.local-postgres"

if [ ! -f "$MIGRATION_MARKER" ]; then
  echo "Robot KB local n'est pas encore marqué MIGRATION_VERIFIED."
  echo "Termine d'abord l'installation/migration vérifiée."
  read -r -p "Appuie sur Entrée pour fermer..."
  exit 2
fi

if [ ! -x "$PYTHON" ]; then
  echo "Runtime Python Robot KB local introuvable."
  echo "Relance Installer Robot KB Local.command."
  read -r -p "Appuie sur Entrée pour fermer..."
  exit 2
fi

PASSWORD="$(security find-generic-password -w -a "$APP_DB_USER" -s "$KEYCHAIN_SERVICE" 2>/dev/null || true)"
if [ -z "$PASSWORD" ]; then
  echo "Mot de passe PostgreSQL Robot KB introuvable dans le Trousseau macOS."
  echo "Relance Installer Robot KB Local.command."
  read -r -p "Appuie sur Entrée pour fermer..."
  exit 2
fi

export ROBOT_KB_VIEWER_PASSWORD="$PASSWORD"
unset PASSWORD

set +e
"$PYTHON" "$SCRIPT_DIR/robot_kb_viewer.py"
status=$?
set -e

unset ROBOT_KB_VIEWER_PASSWORD
exit "$status"
