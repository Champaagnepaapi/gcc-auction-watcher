#!/bin/zsh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
[ -f .env ] || cp .env.example .env
printf '\nInstallation terminée. Édite .env puis lance: ./run.sh\n'
