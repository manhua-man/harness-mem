## 1. Current-truth sync

- [x] 1.1 Update `docs/best-practices.md` to list `wake` as a first-class read tool.
- [x] 1.2 Update the best-practices wake-up section to name `wake(project_name=<project>)` as the default surface.
- [x] 1.3 Update release/status/roadmap writeback to reflect v2.9.16.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects best-practices drift away from the shipped wake surface.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_best_practices_wake_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
