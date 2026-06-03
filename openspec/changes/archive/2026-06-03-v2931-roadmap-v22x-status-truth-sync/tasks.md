## 1. Current-truth sync

- [x] 1.1 Update the top status line in `docs/roadmap-v22x.md` so the v2.2 line is marked complete.
- [x] 1.2 Update release writeback for `v2.9.31`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `roadmap-v22x.md` drifting back to the older `规划中` wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v22x_status_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
