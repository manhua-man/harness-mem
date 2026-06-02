## 1. CLI contract alignment

- [x] 1.1 Update the top-level `cli` spec command set to include `config` and `integration`.
- [x] 1.2 Add explicit maintenance-only requirements for config management and IDE hook installation.

## 2. Release writeback

- [x] 2.1 Update `docs/roadmap-v29.md` and `docs/roadmap-status.md` for the v2.9.3 slice.
- [x] 2.2 Bump version metadata and add a `CHANGELOG.md` entry for v2.9.3.

## 3. Validation

- [x] 3.1 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.2 `python -m ruff check harness_mem tests`
- [x] 3.3 `python -m mypy harness_mem`
- [x] 3.4 `openspec validate --all --strict`
- [x] 3.5 `python -m harness_mem.cli --version`
