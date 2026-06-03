## 1. Current-truth sync

- [x] 1.1 Update root `README.md` to distinguish `openspec/specs/`, `openspec/changes/`, and `openspec/changes/archive/`.
- [x] 1.2 Update `AGENTS.md` repo map to distinguish the same three OpenSpec layers.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.49`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test rejecting the old bucket-style OpenSpec wording in root `README.md` and `AGENTS.md`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_repo_openspec_layout_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
