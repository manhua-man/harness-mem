# Release 0.9.21 (2026-08-20)

## What's shipped

- Physically reorganized repository assets to `code/`:
  - `code/plugins`, `code/mcps`, `code/scripts`, `code/tests`, `code/tools`, `code/crates`
- Kept runtime source-of-truth under `harness_mem/` (Python) and aligned entry/docs to new paths.
- Migrated public MCP/tooling smoke paths and release contracts to the new layout.
- Added clean workspace maintenance script:
  - `code/scripts/clean-workspace.ps1`
- Updated release docs and toolchain wiring for `0.9.21`.
- Preserved `knowledge_entries` as single current-truth authority; candidate/evidence/decision remain job-scoped and are not treated as durable long-term memory.

## Verification completed

- `python -m pytest -q` — **981 passed, 2 skipped**
- `python -m pytest -m "not release_gate"` — **977 passed, 2 skipped, 4 deselected**
- `python -m ruff check harness_mem code`
- `python -m mypy harness_mem`
- `python -m compileall harness_mem`
- `cargo test --workspace`
- `python code/tools/outcome-verifier/scripts/verify_outcomes.py --config .codex/outcomes.json --output .tmp/outcome-verifier/harness-mem-report.json`
  - **Outcome: passed (14/14)**
- `python code/scripts/ensure_mcps_canonical.py`

## Packaging / release status

- `git tag` contains **v0.9.21**.
- Branch clean and aligned to `origin/codex/archive-distill-answer-packets`.
- GitHub Release published: https://github.com/manhua-man/harness-mem/releases/tag/v0.9.21

## One-line clean commands

- `code/scripts/clean-workspace.ps1 -Mode clean`
- `code/scripts/clean-workspace.ps1 -Mode clean-all`
