## 1. Current-truth sync

- [x] 1.1 Update the `docs/roadmap-v29.md` header theme so it reflects the shipped v2.9 release train.
- [x] 1.2 Update the `docs/roadmap-v29.md` goal summary so it distinguishes the initial PRD-sync slice from the later truth-sync slices.
- [x] 1.3 Update release writeback for `v2.9.27`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `roadmap-v29.md` drifting back to the earlier PRD-only top-level summary.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v29_theme_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
