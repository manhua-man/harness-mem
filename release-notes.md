# Release 0.9.22 (2026-08-20)

## What's shipped

- Prevented Goal/Read/Write/Acceptance task templates from becoming long-term
  knowledge.
- Kept normal `search` clean, while allowing the internal Autopilot path to
  inject matching current knowledge into the next agent context.
- Repaired archive receipt verification so a completed job can be readmitted
  only when its exact revision, Note, and receipt prove the same result.
- Added reversible, maintenance-only archival of obsolete current knowledge;
  semantic models cannot request this action.
- Made the outcome verifier read the current SQLite knowledge authority through
  the ordinary search route.

## Verification completed

- `python -m pytest -q` — pending final release run
- `python -m pytest -m "not release_gate"` — pending final release run
- `python -m ruff check harness_mem code/plugins code/tools`
- `python -m mypy harness_mem`
- `python -m compileall harness_mem`
- `cargo test --workspace`
- `python code/tools/outcome-verifier/scripts/verify_outcomes.py --config .codex/outcomes.json --output .tmp/outcome-verifier/harness-mem-report.json`
  - **Outcome: passed (14/14)**
- `python code/scripts/ensure_mcps_canonical.py`

## Packaging / release status

- Pending final commit, tag, and GitHub Release publication.

## One-line clean commands

- `code/scripts/clean-workspace.ps1 -Mode clean`
- `code/scripts/clean-workspace.ps1 -Mode clean-all`
