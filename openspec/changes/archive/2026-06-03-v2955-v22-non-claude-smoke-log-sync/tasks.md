## 1. Current-truth sync

- [x] 1.1 Add a Codex non-Claude smoke entry to `docs/v2-user-test-packet.md`.
- [x] 1.2 Update `docs/roadmap-v22x.md` and `docs/roadmap-status.md` so they say a non-Claude smoke exists but the full manual matrix remains open.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.55`.

## 2. Guardrail

- [x] 2.1 Update the focused regression test so it rejects both overclaiming full closure and stale wording that says non-Claude has never been run.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v22_manual_gate_truth.py tests/test_roadmap_v22x_status_truth.py tests/test_roadmap_status_summary_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
