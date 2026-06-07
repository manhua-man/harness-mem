# Temporal Product Query

Benchmark design for product-level temporal memory behavior.

Status: ready-to-run design for current/history/supersede boundaries. `as_of`
coverage may remain blocked until a stable `as_of` product surface exists.

## Goal

Measure whether the agent can answer temporal memory questions without mixing
current truth, historical truth, supersede chains, and insufficient evidence.

## Run Shape

Each task is run once in the `temporal_guarded` condition.

Allowed:

- current repo/file search
- temporal tests and fixtures
- harness-mem read surfaces when available

Disallowed:

- reporting historical truth as current
- hiding history when explicitly requested
- inventing an `as_of` answer when no stable surface or timestamp evidence exists

## Files

- `prompts.json`: temporal query prompts.
- `acceptance_checklist.md`: pass/fail rubric.
