# Runtime Health Observability

Benchmark design for runtime health, observability, cost discipline, and
regression gates.

Status: blocked-by-product. This design is complete enough to run after v3.4
runtime health and cost surfaces ship.

## Goal

Measure whether the runtime can expose actionable local health, cost, drift, and
regression information without creating a background telemetry system or hiding
false success.

## Unlock Conditions

Run this benchmark only after the product exposes stable versions of:

- runtime health report
- local cost observer or token budget report
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
