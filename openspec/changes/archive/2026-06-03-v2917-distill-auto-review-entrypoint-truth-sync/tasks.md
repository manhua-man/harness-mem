## 1. Current-truth sync

- [x] 1.1 Update `plugins/harness-mem/commands/hm/distill.md` to use `auto_review_candidates(project_name=<project>, apply=true)` as the default review surface.
- [x] 1.2 Update `plugins/harness-mem/skills/harness-mem/SKILL.md` to remove the stale "when available" fallback wording.
- [x] 1.3 Update the MCP distill example to show `auto_review_candidates` summary fields and `applied_decisions`.
- [x] 1.4 Update release/status/roadmap writeback to reflect v2.9.17.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects distill-entrypoint drift back to manual per-item review wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_distill_auto_review_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
