## 1. Current-truth sync

- [x] 1.1 Update `docs/README.md` to point current shipped-state readers at `roadmap-status.md` and `CHANGELOG.md`.
- [x] 1.2 Update release/status/roadmap writeback for `v2.9.51`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test rejecting docs-index wording that omits `roadmap-status.md` and `CHANGELOG.md` as current-truth authorities.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_docs_readme_truth_authority_sync.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
