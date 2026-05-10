#!/bin/bash
# Session Distiller - Bash wrapper for Python script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/session-distill.py"
PYTHON_EXE=""

if command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  for candidate in \
    "/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python313/python.exe" \
    "/mnt/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python313/python.exe" \
    "/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python312/python.exe" \
    "/mnt/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python312/python.exe" \
    "/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python311/python.exe" \
    "/mnt/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python311/python.exe" \
    "/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python310/python.exe" \
    "/mnt/c/Users/${USERNAME}/AppData/Local/Programs/Python/Python310/python.exe"
  do
    if [[ -x "$candidate" ]]; then
      PYTHON_EXE="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_EXE" ]]; then
  echo "No Python interpreter found. Install Python or update session-distill.sh." >&2
  exit 1
fi

exec "$PYTHON_EXE" "$PYTHON_SCRIPT" "$@"
