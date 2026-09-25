#!/usr/bin/env bash
set -e
PY=python3.11
command -v $PY >/dev/null 2>&1 || PY=python3
$PY -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp -n .env.example .env || true
echo ""
echo "Setup complete. Next:"
echo "  1) edit .env and paste your API keys"
echo "  2) source .venv/bin/activate"
echo "  3) python scripts/preflight.py"
