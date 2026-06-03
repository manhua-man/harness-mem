## 1. Current-truth sync

- [x] 1.1 Update `docs/best-practices.md` so `wake` covers common new-session reads.
- [x] 1.2 Rephrase `get_task_handoffs` / `get_confirmed_rules` as drilldown-only wake reads.
- [x] 1.3 Update the daily-workflow spec wording for the best-practices wake boundary.
- [x] 1.4 Update release/status/roadmap writeback for `v2.9.40`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects best-practices drift back to low-level-first wake wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_best_practices_wake_truth.py tests/test_best_practices_wake_drilldown_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
