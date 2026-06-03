## 1. Current-truth sync

- [x] 1.1 Update `docs/README.md` so it distinguishes `openspec/specs/`, `openspec/changes/`, and `openspec/changes/archive/`.
- [x] 1.2 Update release/status/roadmap writeback for `v2.9.47`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test rejecting the old two-directory OpenSpec wording in `docs/README.md`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_docs_readme_openspec_layout_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
