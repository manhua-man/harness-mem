## 1. Current-truth sync

- [x] 1.1 Update `docs/README.md` so `roadmap-v29.md` is described as the shipped v2.9 release train, not just the initial PRD sync slice.
- [x] 1.2 Update `docs/roadmap-status.md` so the v2.9 summary reflects the broader shipped release train.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects v2.9 index summaries drifting back to a PRD-only description.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v29_index_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
