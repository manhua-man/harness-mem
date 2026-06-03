## 1. Current-truth sync

- [x] 1.1 Update `docs/roadmap-v29.md` so the header status tail reaches `v2.9.40`.
- [x] 1.2 Update release/status writeback for `v2.9.41`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `roadmap-v29` header drift back to the `v2.9.39` tail.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v29_theme_truth.py tests/test_roadmap_v29_status_tail_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
