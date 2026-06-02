## 1. Helper integrity

- [x] 1.1 Keep `plugins/harness-mem/scripts/doctor.ps1` on supported maintenance commands only.
- [x] 1.2 Preserve `-Wake` as a hint-only plugin helper behavior, not a removed CLI call.

## 2. Tests

- [x] 2.1 Add an isolated smoke test that runs `doctor.ps1` successfully.
- [x] 2.2 Verify the helper no longer emits `invalid choice: 'status'`.

## 3. Documentation alignment

- [x] 3.1 Align plugin README wording with the repaired helper behavior.
- [x] 3.2 Update `docs/roadmap-v29.md` and status docs for the v2.9.2 slice.

## 4. Validation

- [x] 4.1 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 4.2 `python -m ruff check harness_mem tests`
- [x] 4.3 `python -m mypy harness_mem`
- [x] 4.4 `openspec validate --all --strict`
