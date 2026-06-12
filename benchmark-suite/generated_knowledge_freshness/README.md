# Generated Knowledge Freshness

Benchmark design for generated knowledge cache, source maps, and freshness.

Status: ready-to-run. v3.2 generated knowledge compiler, source-map, atomic
claim, freshness, and compact context surfaces have shipped; benchmark claims
still require artifact-backed results under `benchmark-suite/artifacts/`.

## Goal

Measure whether generated context remains source-mapped, fresh, invalidatable,
and clearly separated from confirmed truth.

## Unlock Conditions

This benchmark is unlocked because the product exposes stable versions of:

- generated knowledge compiler
- source map for generated claims
- atomic claim metadata
- freshness or invalidation metadata
- generated context read surface

## Run Shape

Each task is run once in the `generated_guarded` condition.

Allowed:

- generated knowledge read surface after v3.2 ships
- source-map inspection
- repo/file evidence

Disallowed:

- treating generated prose as confirmed truth
- passing without source-map evidence
- ignoring stale generated cache when underlying truth changes

## Files

- `prompts.json`: generated knowledge tasks.
- `acceptance_checklist.md`: pass/fail rubric.
