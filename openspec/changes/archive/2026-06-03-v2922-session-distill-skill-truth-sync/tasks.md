## 1. Current-truth sync

- [x] 1.1 Update `tools/session-distill/SKILL.md` to use `auto_review_candidates(project_name=<project>, apply=true)` as the default review surface.
- [x] 1.2 Update the plugin README `/hm:distill` summary to mention `auto_review_candidates` directly.
- [x] 1.3 Update release/status/roadmap writeback to reflect v2.9.22.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects session-distill skill drift back to `list_candidates -> confirm/reject` mainline wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_session_distill_skill_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
