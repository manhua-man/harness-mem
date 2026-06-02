## 1. Current-truth sync

- [x] 1.1 Update `plugins/harness-mem/commands/hm/status.md` to use `get_project_status(project_name=<project>)` as the default status surface.
- [x] 1.2 Update the MCP status example to show `phase`, `suggested_slash`, `reason`, and repair hints directly.
- [x] 1.3 Update the daily-workflow spec to guard `/hm:status` against manual low-level read assembly.
- [x] 1.4 Update release/status/roadmap writeback to reflect v2.9.18.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects status-entrypoint drift back to manual low-level read assembly.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_status_entrypoint_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
