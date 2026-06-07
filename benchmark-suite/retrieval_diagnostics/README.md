# Retrieval Diagnostics

Benchmark design for explaining retrieval-quality changes.

Status: ready-to-run design after a retrieval quality delta exists. This pack is
maintainer-facing by default.

## Goal

Localize retrieval gains or regressions to fusion, stem fallback, temporal
handling, candidate ordering, or malformed benchmark scenarios.

## Run Shape

Run this only when there is a concrete retrieval delta to explain. The result
must compare candidate and baseline behavior on the same scenario.

## Files

- `prompts.json`: diagnostic tasks.
- `acceptance_checklist.md`: pass/fail rubric.
