## 1. Current-truth sync

- [x] 1.1 Update `docs/roadmap-v22x.md` to distinguish runtime completion from the still-open manual cross-client gate.
- [x] 1.2 Update `docs/roadmap-status.md` so the v2.2 matrix row and summary carry the same truth.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.54`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test failing if `docs/v2-user-test-packet.md` still reports the non-Claude gap while roadmap docs claim v2.2 is fully completed.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v22_manual_gate_truth.py tests/test_roadmap_v22x_status_truth.py tests/test_roadmap_status_summary_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
