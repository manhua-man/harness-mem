## 1. Runtime behavior

- [x] 1.1 Update `reflection_once(...)` to prefer commands-layer project-root resolution before cwd fallback.
- [x] 1.2 Remove stale TODO/commentary that implied commands-layer resolution was still missing.

## 2. Focused coverage

- [x] 2.1 Add a regression test for known project-root resolution when `project_root` is omitted.
- [x] 2.2 Add a regression test that keeps cwd as the final fallback when no known root exists.

## 3. Release writeback

- [x] 3.1 Update learning-loop spec, roadmap, status, changelog, and version metadata for v2.9.9.

## 4. Validation

- [x] 4.1 `python -m pytest -q tests/test_reflection_once_integration.py tests/test_host_entry_contract.py tests/test_project_root_resolution.py`
- [x] 4.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 4.3 `python -m ruff check harness_mem tests`
- [x] 4.4 `python -m mypy harness_mem`
- [x] 4.5 `openspec validate --all --strict`
- [x] 4.6 `python -m harness_mem.cli --version`
