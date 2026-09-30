#!/usr/bin/env bash
# Hearth — launch from the local venv.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[hearth] first run — setting things up"
    ./install.sh
fi

exec ".venv/bin/python" -m hearth "$@"
