#!/usr/bin/env bash
# Hearth — one-command setup for Linux and macOS.
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    echo "[hearth] python3 not found — install Python 3.10+ first" >&2
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[hearth] creating the local environment"
    "$PY" -m venv .venv
fi

echo "[hearth] installing dependencies"
".venv/bin/python" -m pip install --upgrade pip --quiet
".venv/bin/python" -m pip install -r requirements.txt

echo "[hearth] ready — run ./launch.sh"
