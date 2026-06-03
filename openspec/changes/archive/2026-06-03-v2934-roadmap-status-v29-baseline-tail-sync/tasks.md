## 1. Current-truth sync

- [x] 1.1 Update the top baseline summary in `docs/roadmap-status.md` so the v2.9 train tail matches the current version.
- [x] 1.2 Update release writeback for `v2.9.34`.

## 2. Guardrail

- [x] 2.1 Update the focused baseline regression test so it follows `harness_mem.__version__` instead of a hard-coded tail.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_status_baseline_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
