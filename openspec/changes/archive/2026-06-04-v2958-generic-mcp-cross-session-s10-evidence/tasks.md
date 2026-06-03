## 1. Packet evidence

- [x] 1.1 Run two independent stdio MCP sessions against the same isolated temp home.
- [x] 1.2 Confirm a memory entry in the writer session and verify it surfaces in the reader session `wake` output.
- [x] 1.3 Append the run to `docs/v2-user-test-packet.md`.

## 2. Guardrail and writeback

- [x] 2.1 Add a focused regression test for the cross-session entry.
- [x] 2.2 Update release writeback for `v2.9.58`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v2_user_test_packet_cross_session_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
