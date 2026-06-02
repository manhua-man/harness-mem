## 1. Current-truth sync

- [x] 1.1 Update the README distill workflow diagram to use `auto_review_candidates(apply=true)` as the review surface.
- [x] 1.2 Update release/status/roadmap writeback to reflect v2.9.20.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects README drift back to `list_candidates -> auto-review / confirm / reject`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_readme_distill_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
