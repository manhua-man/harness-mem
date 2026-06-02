## 1. PRD sync contract

- [x] 1.1 Formalize `/hm:prd-sync [--apply]` as a user-facing maintenance entry.
- [x] 1.2 Define dry-run default and candidate-only write boundary.
- [x] 1.3 Keep PRD sync outside canonical truth mutation and direct PRD/roadmap edits.

## 2. Implementation and tests

- [x] 2.1 Make `prd-sync` callable without project resolution.
- [x] 2.2 Tighten candidate output so `--apply` writes only `prd-distilled/*.md`.
- [x] 2.3 Add focused tests for no-bundles, dry-run, apply, and bundled-only scanning.

## 3. Documentation alignment

- [x] 3.1 Add `prd-sync` to maintenance-entry docs and plugin command docs.
- [x] 3.2 Add `docs/roadmap-v29.md` and surface it from doc indexes/status.

## 4. Validation

- [x] 4.1 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 4.2 `python -m ruff check harness_mem tests tools/session-distill/bin/session-distill.py`
- [x] 4.3 `python -m mypy harness_mem`
- [x] 4.4 `openspec validate --all --strict`
