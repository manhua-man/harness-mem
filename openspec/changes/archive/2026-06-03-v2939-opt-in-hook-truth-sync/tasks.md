## 1. Current-truth sync

- [x] 1.1 Update `README.md` and `AGENTS.md` so they describe hooks as opt-in and default-off rather than absent.
- [x] 1.2 Update release writeback for `v2.9.39`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `README.md` / `AGENTS.md` drifting back to the older absolute no-hook wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_opt_in_hook_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
