## 1. Current-truth sync

- [x] 1.1 Update `/hm:wake` command docs to use MCP `wake(project_name=<project>)` as the default path.
- [x] 1.2 Update repo-local `harness-mem` skill wake guidance to use `get_project_status` + `wake(...)`.
- [x] 1.3 Update release/status/roadmap writeback to reflect v2.9.15.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the old manual wake choreography in current repo-local guidance.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_wake_entrypoint_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
