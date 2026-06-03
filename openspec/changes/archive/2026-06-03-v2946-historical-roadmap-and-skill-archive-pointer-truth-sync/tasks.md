## 1. Current-truth sync

- [x] 1.1 Update `docs/roadmap-v16x.md` to point completed `v161` status link at the archive path.
- [x] 1.2 Update `docs/roadmap-v17x.md` to point completed `v170`–`v173` slices at archive paths.
- [x] 1.3 Update `docs/roadmap-v23.md` to point `v231` at the archive path.
- [x] 1.4 Update `tools/session-distill/SKILL.md` to point at archived `v230` design and current `openspec/specs/metabolism/spec.md`.
- [x] 1.5 Update release/status/roadmap writeback for `v2.9.46`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test rejecting stale active-change paths and nonexistent `memory-metabolism` main-spec references in these high-visibility docs.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_historical_archive_pointer_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
