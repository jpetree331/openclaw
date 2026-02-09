#!/usr/bin/env bash
# Run the Drive Playground service with a local venv (avoids system pip/python issues).
# From repo root: scripts/drive_playground/run.sh
# Or from here: ./run.sh

set -e
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating .venv and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and set DRIVE_PLAYGROUND_FOLDER_ID and DRIVE_PLAYGROUND_API_KEY."
  echo "You also need credentials.json (Google OAuth client) in this directory."
  exit 1
fi

exec .venv/bin/python drive_playground_service.py
