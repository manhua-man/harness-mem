## 1. Current-truth sync

- [x] 1.1 Update v2.4 roadmap host-entry examples to the shipped `python -m harness_mem.host_entry` invocation form.
- [x] 1.2 Update release/status/roadmap writeback to reflect v2.9.13.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects placeholder or stale host-entry invocation forms in current-truth docs.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_host_entry_module_truth.py tests/test_host_entry_cli.py tests/test_install_cursor_hook.py tests/test_install_claude_hook.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
