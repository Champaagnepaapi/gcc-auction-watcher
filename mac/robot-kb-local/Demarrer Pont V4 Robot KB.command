#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_ROOT="${ROBOT_KB_LOCAL_ROOT:-$HOME/Library/Application Support/RobotPokemonKB}"
VENV_DIR="$DATA_ROOT/venv"
DB_SERVICE="RobotPokemonKB.local-postgres"
DB_ACCOUNT="robotpokemon_kb"
BRIDGE_SERVICE="RobotPokemonKB.v4-readonly-bridge"
BRIDGE_ACCOUNT="robotpokemon_kb"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Runtime Robot KB local absent. Relance Installer Robot KB Local.command." >&2
  exit 2
fi

DB_PASSWORD="$(security find-generic-password -w -a "$DB_ACCOUNT" -s "$DB_SERVICE" 2>/dev/null || true)"
if [ -z "$DB_PASSWORD" ]; then
  echo "Mot de passe PostgreSQL Robot KB absent du Trousseau." >&2
  exit 3
fi

BRIDGE_TOKEN="$(security find-generic-password -w -a "$BRIDGE_ACCOUNT" -s "$BRIDGE_SERVICE" 2>/dev/null || true)"
if [ -z "$BRIDGE_TOKEN" ]; then
  echo "Aucun token de pont configuré. Saisis un token aléatoire d'au moins 24 caractères." >&2
  printf "Token du pont (saisie masquée) : "
  IFS= read -r -s BRIDGE_TOKEN
  printf "\n"
  if [ "${#BRIDGE_TOKEN}" -lt 24 ]; then
    echo "Token trop court; rien n'a été enregistré." >&2
    exit 4
  fi
  security add-generic-password -U -a "$BRIDGE_ACCOUNT" -s "$BRIDGE_SERVICE" -w "$BRIDGE_TOKEN" >/dev/null
  echo "Token enregistré uniquement dans le Trousseau macOS."
fi

export ROBOT_KB_V4_BRIDGE_DB_PASSWORD="$DB_PASSWORD"
export ROBOT_KB_V4_BRIDGE_TOKEN="$BRIDGE_TOKEN"
unset DB_PASSWORD BRIDGE_TOKEN

exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/robot_kb_v4_readonly_bridge.py"
