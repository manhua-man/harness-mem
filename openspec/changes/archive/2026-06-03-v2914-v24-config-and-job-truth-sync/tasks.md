## 1. Current-truth sync

- [x] 1.1 Update v2.4 roadmap config-loader wording to the shipped recognized-key scope.
- [x] 1.2 Update v2.4 roadmap queue-model wording to the shipped single-ReflectionJob model.
- [x] 1.3 Update release/status/roadmap writeback to reflect v2.9.14.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects `project_name` / `active_project.txt` loader claims and `ReviewJob` schema claims in current-truth docs.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_v24_config_and_job_truth.py tests/test_load_merged_config.py tests/test_reflection_job_schema.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
