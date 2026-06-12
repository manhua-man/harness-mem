#!/usr/bin/env bash
# Build a public source tarball from HEAD, then strip maintainer-only paths.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "Run from a git checkout of harness-mem (missing .git)." >&2
  exit 1
fi

VERSION="$(python -c 'from harness_mem import __version__; print(__version__)')"
DIST="$ROOT/dist"
mkdir -p "$DIST"
PREFIX="harness-mem-${VERSION}/"
OUT="$DIST/harness-mem-${VERSION}-public-source.tar.gz"

git archive --format=tar.gz -o "$OUT" --prefix="$PREFIX" HEAD
python "$ROOT/scripts/filter_public_archive.py" "$OUT"
python "$ROOT/scripts/filter_public_archive.py" "$OUT" --check-only

echo "Wrote $OUT (maintainer-only paths removed per release/public-source-excludes.txt)"
