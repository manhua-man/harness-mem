## 1. Guardrail

- [x] 1.1 Add a focused regression test covering README, MCP spec, telemetry spec, and the v2 user-test packet.

## 2. Release writeback

- [x] 2.1 Update roadmap, status, changelog, and version metadata for v2.9.8.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_maintenance_surface_collateral.py tests/test_stale_cli_surface.py tests/test_shell_completion.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`

