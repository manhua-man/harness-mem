## 1. Current-truth sync

- [x] 1.1 Update `docs/best-practices.md` to use `auto_review_candidates(project_name=<project>, apply=true)` as the default distill review surface.
- [x] 1.2 Update the runtime tool catalog so `auto_review_candidates` is the default management tool and `list_candidates` becomes explicit drilldown/recheck tooling.
- [x] 1.3 Update release/status/roadmap writeback to reflect v2.9.19.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects best-practices drift back to per-item distill review wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_best_practices_auto_review_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
