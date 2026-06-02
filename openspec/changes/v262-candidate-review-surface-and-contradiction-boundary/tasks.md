## 1. Review surface

- [x] 1.1 Extend `list_candidates` payload gathering to include merge suggestions.
- [x] 1.2 Extend `list_candidates` payload gathering to include stale-truth suggestions.
- [x] 1.3 Add serializers and counts for the two suggestion types.

## 2. Boundary

- [x] 2.1 Define contradiction/stale suggestion boundaries for wiki/generated evidence.
- [x] 2.2 Keep suggestion visibility separate from default truth surfaces.

## 3. Validation

- [x] 3.1 Add focused MCP tests for review-surface visibility.
- [x] 3.2 Run `python -m pytest -q` or targeted equivalents.
- [x] 3.3 Run `python -m ruff check harness_mem tests`.
- [x] 3.4 Run `python -m mypy harness_mem`.
