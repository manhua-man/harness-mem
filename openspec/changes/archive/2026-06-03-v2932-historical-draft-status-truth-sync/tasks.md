## 1. Current-truth sync

- [x] 1.1 Update the dream-absorption draft status block so it is clearly marked as a historical draft archive.
- [x] 1.2 Update `docs/README.md` so `docs/roadmap/` is described as historical proposals / design drafts.
- [x] 1.3 Update release writeback for `v2.9.32`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the historical draft drifting back to a bare `draft` status.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_historical_draft_status_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
