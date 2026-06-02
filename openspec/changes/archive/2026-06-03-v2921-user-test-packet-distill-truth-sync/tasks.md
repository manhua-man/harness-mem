## 1. Current-truth sync

- [x] 1.1 Update the v2 user test packet generic distill chain to use `auto_review_candidates` directly after `suggest_*`.
- [x] 1.2 Update release/status/roadmap writeback to reflect v2.9.21.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects v2 user test packet drift back to `list_candidates -> auto_review_candidates`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v2_user_test_packet_distill_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
