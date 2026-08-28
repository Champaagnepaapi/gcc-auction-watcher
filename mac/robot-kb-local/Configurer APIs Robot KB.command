#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT="robotpokemon_kb"
POKETRACE_SERVICE="RobotPokemonKB.poketrace-api"
PPT_SERVICE="RobotPokemonKB.ppt-api"
EBAY_RAPIDAPI_SERVICE="RobotPokemonKB.ebay-rapidapi"
RUNNER="$SCRIPT_DIR/robot_kb_local_runner.sh"

trim_secret() {
  # API keys do not contain surrounding whitespace. Remove accidental copy/paste
  # spaces/newlines without ever echoing the key to the terminal.
  printf '%s' "$1" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

poketrace_status() {
  local key="$1"
  curl -sS -o /dev/null -w '%{http_code}' \
    -H "X-API-Key: $key" \
    -H 'Accept: application/json' \
    --connect-timeout 10 --max-time 20 \
    'https://api.poketrace.com/v1/auth/info' || true
}

ppt_status() {
  local key="$1"
  curl -sS -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $key" \
    -H 'Accept: application/json' \
    --connect-timeout 10 --max-time 20 \
    'https://www.pokemonpricetracker.com/api/v2/sets?language=english' || true
}

ebay_rapidapi_status() {
  local key="$1"
  curl -sS -o /dev/null -w '%{http_code}' \
    -X POST \
    -H 'Content-Type: application/json' \
    -H 'x-rapidapi-host: ebay-average-selling-price.p.rapidapi.com' \
    -H "x-rapidapi-key: $key" \
    --data '{"keywords":"Pokemon Pikachu PSA 10","max_search_results":60,"remove_outliers":false,"site_id":"0"}' \
    --connect-timeout 10 --max-time 30 \
    'https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems' || true
}

configure_key() {
  local label="$1"
  local service="$2"
  local validator="$3"
  local current status candidate

  current="$(security find-generic-password -w -a "$ACCOUNT" -s "$service" 2>/dev/null || true)"
  if [ -n "$current" ]; then
    status="$($validator "$current")"
    if [ "$status" = "200" ]; then
      echo "$label : clé actuelle VALIDÉE (HTTP 200)."
      unset current status
      return 0
    fi
    echo "$label : clé actuelle refusée par le fournisseur (HTTP ${status:-000})."
  else
    echo "$label : aucune clé enregistrée."
  fi

  printf "%s API key brute uniquement (saisie masquée, entrée vide = annuler) : " "$label"
  IFS= read -r -s candidate
  printf '\n'
  candidate="$(trim_secret "$candidate")"

  # Tolerate common copy/paste prefixes while still storing only the raw key.
  case "$label" in
    PokeTrace)
      candidate="${candidate#X-API-Key:}"
      candidate="$(trim_secret "$candidate")"
      ;;
    PokemonPriceTracker)
      candidate="${candidate#Authorization: Bearer }"
      candidate="${candidate#Bearer }"
      candidate="$(trim_secret "$candidate")"
      ;;
    eBayRapidAPI)
      candidate="${candidate#x-rapidapi-key:}"
      candidate="${candidate#X-RapidAPI-Key:}"
      candidate="$(trim_secret "$candidate")"
      ;;
  esac

  if [ -z "$candidate" ]; then
    echo "$label : aucune modification."
    unset current status candidate
    return 1
  fi

  status="$($validator "$candidate")"
  if [ "$status" != "200" ]; then
    echo "$label : clé NON enregistrée, fournisseur HTTP ${status:-000}."
    echo "Vérifie que tu as copié la clé API brute depuis le dashboard du fournisseur."
    unset current status candidate
    return 1
  fi

  security add-generic-password -U -a "$ACCOUNT" -s "$service" -w "$candidate" >/dev/null
  echo "$label : clé VALIDÉE et remplacée dans le Trousseau macOS uniquement."
  unset current status candidate
  return 0
}

if [ "${1:-}" = "ebay" ]; then
  ebay_ok=false
  configure_key "eBayRapidAPI" "$EBAY_RAPIDAPI_SERVICE" ebay_rapidapi_status && ebay_ok=true || true
  echo
  if [ "$ebay_ok" = true ]; then
    echo "Lancement d'un probe eBay SOLD shadow en lecture seule..."
    if /bin/bash "$RUNNER" ebay-probe; then
      echo "Probe eBay SOLD shadow terminé. Aucune donnée n'a été promue en preuve SOLD V4."
    else
      echo "Le probe eBay a signalé une erreur fournisseur. Aucune clé n'est loggée." >&2
      exit 2
    fi
  else
    echo "Aucune clé eBay RapidAPI valide confirmée ; aucun probe lancé." >&2
    exit 1
  fi
  exit 0
fi

pt_ok=false
ppt_ok=false
configure_key "PokeTrace" "$POKETRACE_SERVICE" poketrace_status && pt_ok=true || true
configure_key "PokemonPriceTracker" "$PPT_SERVICE" ppt_status && ppt_ok=true || true

echo
if [ "$pt_ok" = true ] || [ "$ppt_ok" = true ]; then
  echo "Lancement immédiat d'un rattrapage provider Robot KB..."
  if /bin/bash "$RUNNER" paid; then
    echo "Rattrapage provider terminé."
  else
    echo "Le rattrapage a signalé une erreur fournisseur. Lis uniquement les codes/notes affichés ; aucune clé n'est loggée." >&2
    exit 2
  fi
else
  echo "Aucune clé valide confirmée ; aucun appel de harvest lancé." >&2
  exit 1
fi
