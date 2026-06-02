## 1. Completion surface sync

- [x] 1.1 Update shell completion generators to include `config` and `integration`.
- [x] 1.2 Keep `qs` visible across shell completion outputs.
- [x] 1.3 Add completion support for `config` / `integration` second-level actions.

## 2. Verification and docs

- [x] 2.1 Add focused tests for generated completion scripts and CLI `--completion`.
- [x] 2.2 Update roadmap, status, changelog, and version metadata for v2.9.5.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_shell_completion.py tests/cli/test_cli_entrypoint.py tests/test_cli_scope_guard.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
