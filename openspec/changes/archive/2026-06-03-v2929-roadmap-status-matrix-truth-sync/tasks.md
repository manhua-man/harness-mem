## 1. Current-truth sync

- [x] 1.1 Update historical rows in `docs/roadmap-status.md` so obsolete `当前收口基线` labels are replaced with current-truth `已完成`.
- [x] 1.2 Update release writeback for `v2.9.29`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects historical rows drifting back to stale `当前收口基线` labels.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_status_matrix_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
