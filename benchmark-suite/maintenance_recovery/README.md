# Maintenance Recovery

Benchmark design for operational recovery from broken or stale local state.

Status: ready-to-run design for maintenance-console recovery paths. This is
different from automatic maintenance effectiveness, which remains blocked by
future opt-in dream surfaces.

## Goal

Measure whether local maintenance tools diagnose and recover broken state
without false success or obsolete daily-workflow guidance.

## Run Shape

Each task is run once in the `recovery` condition against a controlled broken
or stale fixture.

Required controls:

- input state description
- command or tool transcript
- before/after state
- recovery notes
- false-success check

## Files

- `prompts.json`: maintenance recovery tasks.
- `acceptance_checklist.md`: pass/fail rubric.
