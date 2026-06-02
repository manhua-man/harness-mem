## 1. Current-truth sync

- [x] 1.1 Update `docs/roadmap-v22x.md` so the distill closed-loop contract points to `auto_review_candidates(apply=true)`.
- [x] 1.2 Update release/status/roadmap writeback to reflect v2.9.24.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects roadmap-v22x drift back to the older distill mainline.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_roadmap_v22x_distill_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
