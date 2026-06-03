## 1. Current-truth sync

- [x] 1.1 Update the short summary in `docs/roadmap-status.md` so it summarizes the completed line from `v1.5` through `v2.9`.
- [x] 1.2 Update release writeback for `v2.9.36`.

## 2. Guardrail

- [x] 2.1 Update the focused summary regression test so it rejects drifting back to the older `v2.2`-only framing.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_status_summary_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
