## 1. Packet evidence

- [x] 1.1 Run the packet-defined stale-CLI scan command against the specified doc scope.
- [x] 1.2 Record the observed hits and allowed boundary in `docs/v2-user-test-packet.md`.

## 2. Guardrail and writeback

- [x] 2.1 Add a focused regression test for the stale-CLI packet entry.
- [x] 2.2 Update release writeback for `v2.9.60`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v2_user_test_packet_stale_cli_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
