#!/bin/zsh
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
python watcher.py >> watcher.log 2>&1
