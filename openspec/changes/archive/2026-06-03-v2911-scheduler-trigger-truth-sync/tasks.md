## 1. Current-truth sync

- [x] 1.1 Update v2.4 roadmap wording from `off|cron` to the shipped `off|on` gate for `triggers.scheduler`.
- [x] 1.2 Clarify the operator doc wording in `docs/cli/v2.4.md`.
- [x] 1.3 Update roadmap/status/release writeback to reflect v2.9.11.

## 2. Guardrail

- [x] 2.1 Extend the focused config-truth regression test to cover `triggers.scheduler`.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_worker_mode_truth.py tests/test_load_merged_config.py tests/test_cli_config_validate.py tests/test_config_writer.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
