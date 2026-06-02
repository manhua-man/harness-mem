## Why

`/hm:status` is already a user-visible command surface: it appears in README,
plugin docs, install output, and command instructions. But today its contract
is not versioned in OpenSpec, and the repo even contains a user-facing wording
split: one doc says it delegates to `doctor`, while the actual command
instruction is a read-only MCP triage flow built around `get_project_status`.

That leaves the most basic "what should I do next?" memory entrypoint governed
by prompt convention instead of a formal runtime contract.

## What Changes

- Add a formal contract for `/hm:status` as a read-only project triage entry.
- Extend MCP `get_project_status` to return slash-native triage hints:
  `phase`, `suggested_slash`, `reason`, and optional repair hints.
- Keep `/hm:review` repair-only even when pending candidates exist: status may
  hint it, but should not elevate it to the main happy-path next step.
- Align plugin docs and command docs with the real MCP-driven behavior.

## Impact

- `/hm:status` becomes a versioned user-facing surface instead of an implicit
  prompt pattern.
- Agent clients can reuse structured next-step hints instead of hardcoding
  their own status interpretation.
- The repo no longer presents contradictory status UX between plugin README and
  command instructions.
