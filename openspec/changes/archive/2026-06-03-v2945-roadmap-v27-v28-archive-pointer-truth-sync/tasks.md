## 1. Current-truth sync

- [x] 1.1 Update `docs/roadmap-v27.md` so completed `v270`–`v272` slices point at archive paths.
- [x] 1.2 Update `docs/roadmap-v28.md` so completed `v280`–`v282` slices point at archive paths.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.45`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects stale active-change pointers in those `v2.7` / `v2.8` roadmap docs.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v27_v28_archive_pointer_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
