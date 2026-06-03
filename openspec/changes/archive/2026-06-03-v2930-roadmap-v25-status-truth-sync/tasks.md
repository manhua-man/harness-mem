## 1. Current-truth sync

- [x] 1.1 Update the top status line in `docs/roadmap-v25.md` so the v2.5 line is marked complete.
- [x] 1.2 Update the `v2.5.2` section so it no longer says the slice is pending release.
- [x] 1.3 Update release writeback for `v2.9.30`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `roadmap-v25.md` drifting back to `进行中 / 待发版` wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v25_status_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
