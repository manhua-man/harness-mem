#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

: "${TMPDIR:=$PWD/.tmp/pytest-tmp}"
export TMPDIR
mkdir -p "$TMPDIR"
pytest_base_temp="$PWD/.tmp/pytest-full-$(date +%Y%m%d%H%M%S)"

echo "Running pytest full..."
python -m pytest -q -p no:cacheprovider --basetemp "$pytest_base_temp"

echo "Running ruff..."
python -m ruff check .

echo "Running mypy..."
python -m mypy harness_mem

echo "Running benchmark release artifact check..."
python benchmark-suite/tools/check_release_artifacts.py
