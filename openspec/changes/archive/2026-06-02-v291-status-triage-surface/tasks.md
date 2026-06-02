## 1. Status contract

- [x] 1.1 Formalize `/hm:status` as a read-only project triage entry.
- [x] 1.2 Define structured next-step hints for empty, ready, and repair-hint states.
- [x] 1.3 Keep `/hm:review` repair-only even when pending candidates exist.

## 2. Implementation and tests

- [x] 2.1 Extend MCP `get_project_status` with `phase`, `suggested_slash`, and `reason`.
- [x] 2.2 Add optional review hint fields without making review the default happy-path step.
- [x] 2.3 Add focused MCP tests for ready, empty, and pending-candidate states.

## 3. Documentation alignment

- [x] 3.1 Align plugin README and `/hm:status` command docs with the MCP-driven triage behavior.
- [x] 3.2 Update `docs/roadmap-v29.md` and status docs for the v2.9.1 slice.

## 4. Validation

- [x] 4.1 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 4.2 `python -m ruff check harness_mem tests tools/session-distill/bin/session-distill.py`
- [x] 4.3 `python -m mypy harness_mem`
- [x] 4.4 `openspec validate --all --strict`
