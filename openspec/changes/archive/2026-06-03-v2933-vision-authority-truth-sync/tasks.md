## 1. Current-truth sync

- [x] 1.1 Update the vision-doc status block so it is clearly marked as a historical archive.
- [x] 1.2 Update `docs/reference-projects.md` so current version truth points to `roadmap-status` and `CHANGELOG`.
- [x] 1.3 Update `docs/README.md` so the vision doc is described as a historical direction.
- [x] 1.4 Update release writeback for `v2.9.33`.

## 2. Guardrail

- [x] 2.1 Add a focused regression test that rejects the vision/reference docs drifting back to the older authority wording.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_vision_authority_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
