#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="/Users/maximilian/PycharmProjects/claudeAutoAccept"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
TARGET_SCRIPT="$SCRIPT_DIR/xcode_build_click.py"

exec "$PYTHON_BIN" "$TARGET_SCRIPT" --app-name Xcode --threshold 0.8 "$@"
