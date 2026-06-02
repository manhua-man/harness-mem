## 1. Guardrail sync

- [x] 1.1 Update the stale CLI surface regression test to recognize the current maintenance command set.
- [x] 1.2 Keep the test focused on forbidding removed daily-memory verbs, not supported maintenance verbs.

## 2. Release writeback

- [x] 2.1 Update `docs/roadmap-v29.md` and `docs/roadmap-status.md` for the v2.9.4 slice.
- [x] 2.2 Bump version metadata and add a `CHANGELOG.md` entry for v2.9.4.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_stale_cli_surface.py tests/cli/test_cli_entrypoint.py tests/test_cli_scope_guard.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`

