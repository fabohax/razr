#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
SPEC_FILE="$ROOT_DIR/razr-gui.spec"
GUI_ENTRY="$ROOT_DIR/gui.py"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Virtual environment not found at $ROOT_DIR/.venv"
    echo "Create it first with: python3 -m venv .venv"
    exit 1
fi

BUILD_TARGET="$SPEC_FILE"
EXTRA_ARGS=()

if [[ ! -f "$SPEC_FILE" ]]; then
    if [[ ! -f "$GUI_ENTRY" ]]; then
        echo "Spec file not found: $SPEC_FILE"
        echo "GUI entry point not found either: $GUI_ENTRY"
        exit 1
    fi

    echo "Spec file not found. Falling back to gui.py..."
    BUILD_TARGET="$GUI_ENTRY"
    EXTRA_ARGS=(--onefile --name razr-gui)
fi

cd "$ROOT_DIR"

echo "Building razr-gui with PyInstaller..."
"$VENV_PYTHON" -m PyInstaller --noconfirm "${EXTRA_ARGS[@]}" "$BUILD_TARGET"

echo
echo "Build complete: $ROOT_DIR/dist/razr-gui"