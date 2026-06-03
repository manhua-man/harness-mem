## 1. Current-truth sync

- [x] 1.1 Update the `docs/README.md` index entry for `roadmap-status.md` so it covers `v1.5` through `v2.9`.
- [x] 1.2 Update release writeback for `v2.9.35`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the docs index drifting back to the older `v1.6` range.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_docs_readme_status_range_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
