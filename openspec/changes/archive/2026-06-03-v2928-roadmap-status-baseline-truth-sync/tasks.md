## 1. Current-truth sync

- [x] 1.1 Update the top baseline summary in `docs/roadmap-status.md` so it reflects the shipped `v2.9.0–v2.9.27` release train.
- [x] 1.2 Update release writeback for `v2.9.28`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the high-visibility baseline summary drifting back to the earlier `v2.9.11` cutoff wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_status_baseline_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
