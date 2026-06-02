## 1. Collateral sync

- [x] 1.1 Update README maintenance-console summary to include `config` and `integration`.
- [x] 1.2 Update telemetry spec command coverage to include the current maintenance surface.
- [x] 1.3 Remove duplicated v2.9 summary wording from `docs/roadmap-status.md`.

## 2. Release writeback

- [x] 2.1 Update roadmap, status, changelog, and version metadata for v2.9.7.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_stale_cli_surface.py tests/test_shell_completion.py tests/cli/test_cli_entrypoint.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`

