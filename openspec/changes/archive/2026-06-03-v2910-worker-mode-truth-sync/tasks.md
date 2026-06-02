## 1. Current-truth sync

- [x] 1.1 Update v2.4 roadmap wording from `worker.mode=daemon` to the shipped `worker.mode=on` gate.
- [x] 1.2 Update roadmap-status non-goal wording so it no longer teaches `worker.mode=daemon`.
- [x] 1.3 Clarify the operator doc wording in `docs/cli/v2.4.md`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that ties docs back to `_RECOGNIZED_KEYS` for `worker.mode`.

## 3. Release writeback

- [x] 3.1 Update `docs/roadmap-v29.md`, `docs/roadmap-status.md`, `CHANGELOG.md`, and version metadata for v2.9.10.

## 4. Validation

- [x] 4.1 `python -m pytest -q tests/test_worker_mode_truth.py tests/test_load_merged_config.py tests/test_cli_config_validate.py tests/test_config_writer.py`
- [x] 4.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 4.3 `python -m ruff check harness_mem tests`
- [x] 4.4 `python -m mypy harness_mem`
- [x] 4.5 `openspec validate --all --strict`
- [x] 4.6 `python -m harness_mem.cli --version`
