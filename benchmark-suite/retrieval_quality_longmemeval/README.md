# Retrieval Quality LongMemEval

Benchmark design for durable retrieval-quality baselines.

Status: ready-to-run design. Existing historical results live under
`docs/benchmark/`; new runs should produce artifact bundles under
`benchmark-suite/artifacts/`.

## Goal

Measure retrieval quality for the current retrieval stack on LongMemEval-style
questions, with explicit mode, split, top-k, runtime, and per-type breakdown.

## Run Shape

Run one or more fixed retrieval modes against a fixed dataset snapshot.

Required controls:

- exact dataset path
- exact command line
- exact retrieval mode
- exact top-k
- repo state
- embedding model and fallback state

## Files

- `prompts.json`: retrieval tasks and mode definitions.
- `acceptance_checklist.md`: pass/fail rubric.
