# Runtime Health Observability

Benchmark design for runtime health, observability, cost discipline, and
regression gates.

Status: ready-to-run. v3.4.4 ships the local MCP surface cost observer,
runtime health, drift, budget policy, and regression gate report surfaces.

## Goal

Measure whether the runtime can expose actionable local health, cost, drift, and
regression information without creating a background telemetry system or hiding
false success.

## Unlock Conditions

Run this benchmark against the stable v3.4.4 surfaces:

- runtime health report
- local cost observer and token budget report
- version drift visibility
- benchmark regression gate report
- failure or false-success reporting

## Run Shape

Each task is run once in the `health_guarded` condition.

Allowed:

- local doctor/health surfaces
- benchmark-suite artifacts
- repo/file evidence

Disallowed:

- cloud telemetry requirements
- treating cost as an observability sub-item
- reporting success without checking expected failure modes

## Files

- `prompts.json`: runtime health tasks.
- `acceptance_checklist.md`: pass/fail rubric.
