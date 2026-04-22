#!/bin/bash
# Session Distiller - portable shell wrapper for the Python CLI

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/session-distill.py"

if command -v python3 >/dev/null 2>&1; then
  exec "$(command -v python3)" "$PYTHON_SCRIPT" "$@"
elif command -v python >/dev/null 2>&1; then
  exec "$(command -v python)" "$PYTHON_SCRIPT" "$@"
elif command -v py >/dev/null 2>&1; then
  exec py -3 "$PYTHON_SCRIPT" "$@"
else
  echo "session-distill: Python 3 was not found in PATH." >&2
  exit 1
fi
