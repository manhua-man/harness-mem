## 1. Current-truth sync

- [x] 1.1 Update root `README.md` to point current shipped-state readers at `docs/roadmap-status.md` and `CHANGELOG.md`.
- [x] 1.2 Update `AGENTS.md` to point current shipped-state readers at the same authority pair.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.50`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test rejecting root-entry wording that omits `docs/roadmap-status.md` and `CHANGELOG.md` as current-truth authorities.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_root_truth_authority_sync.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
