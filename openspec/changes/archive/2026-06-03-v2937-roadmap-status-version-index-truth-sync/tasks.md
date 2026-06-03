## 1. Current-truth sync

- [x] 1.1 Update the high-visibility version index in `docs/roadmap-status.md` so it covers `v1.5.x` through `v2.9.x`.
- [x] 1.2 Rename the section label from `后续 Roadmap` to `版本索引`.
- [x] 1.3 Update release writeback for `v2.9.37`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the version index drifting back to the older `v2.2.x` starting point.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_status_version_index_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
