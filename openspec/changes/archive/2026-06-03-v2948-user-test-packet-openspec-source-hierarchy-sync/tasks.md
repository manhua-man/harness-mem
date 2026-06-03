## 1. Current-truth sync

- [x] 1.1 Update `docs/v2-user-test-packet.md` so it points readers at `openspec/specs/...` by default.
- [x] 1.2 Keep `openspec/changes/<change>/specs/...` only as a conditional drilldown when an active change proposal exists.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.48`.

## 2. Guardrail

- [x] 2.1 Extend the focused regression test so `v2-user-test-packet` cannot regress to treating change-local specs as a generic default landing path.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v2_user_test_packet_contract_source_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
