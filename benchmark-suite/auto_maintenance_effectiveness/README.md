# Auto Maintenance Effectiveness

Benchmark design for the opt-in automatic memory maintenance loop.

Status: ready-to-run. v3.1 Auto Dream Memory Maintenance now exposes the
explicit opt-in maintenance loop; this design still needs a completed artifact
bundle before any effectiveness claim is supported.

## Goal

Measure whether automatic maintenance improves memory quality without silent
truth mutation, unreviewable changes, or irrecoverable false positives.

## Unlock Conditions

The product now exposes stable versions of:

- explicit opt-in maintenance trigger such as `/hm:dream`
- dream or maintenance ledger
- apply/reject/undo path
- audit trail for every maintenance action

## Run Shape

Each task is run once in the `maintenance_guarded` condition.

Allowed:

- explicit maintenance trigger
- candidate review or ledger read surfaces
- before/after store inspection

Disallowed:

- silent confirmed-truth mutation
- benchmark pass without audit trail
- hiding false positives or undo failures

## Files

- `prompts.json`: maintenance tasks.
- `acceptance_checklist.md`: pass/fail rubric.
