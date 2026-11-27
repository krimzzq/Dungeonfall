#!/usr/bin/env bash
set -e

cd -- "$(dirname -- "$0")"

PYTHON=".venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    python3 -m venv .venv || {
        echo 'Could not create a virtual environment. On Ubuntu, install python3-full.' >&2
        exit 1
    }
fi

if ! "$PYTHON" -c "from importlib.metadata import version; assert version('pygame-ce') == '2.5.8'" >/dev/null 2>&1; then
    "$PYTHON" -m pip install -r requirements.txt
fi

exec "$PYTHON" main.py
