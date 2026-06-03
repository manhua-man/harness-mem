## 1. Current-truth sync

- [x] 1.1 Update `docs/v2-user-test-packet.md` to point at `openspec/specs/daily-workflow/spec.md`.
- [x] 1.2 Rewrite the Codex MCP wording in the packet to repo-owned stdio contract language.
- [x] 1.3 Update release/status/roadmap writeback for `v2.9.43`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the archived change path and the drifting client-version wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v2_user_test_packet_distill_truth.py tests/test_v2_user_test_packet_contract_source_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
