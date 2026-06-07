#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running pytest full..."
python -m pytest -q

echo "Running ruff..."
python -m ruff check .

echo "Running mypy..."
python -m mypy harness_mem

echo "Running openspec..."
openspec validate --all --strict
