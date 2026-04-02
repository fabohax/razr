#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Virtual environment not found at $ROOT_DIR/.venv"
    echo "Create it first with: python3 -m venv .venv"
    exit 1
fi

cd "$ROOT_DIR"

echo "Building razr-gui with PyInstaller..."
"$VENV_PYTHON" -m PyInstaller --onefile --name razr-gui gui.py

echo
echo "Build complete: $ROOT_DIR/dist/razr-gui"