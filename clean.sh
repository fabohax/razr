#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR"

echo "Removing PyInstaller artifacts..."
rm -rf build dist
rm -f ./*.spec

echo "Clean complete."