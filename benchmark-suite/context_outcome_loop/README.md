# Context Outcome Loop

Status: deterministic loop-harness gate, not a public quality benchmark.

This collection tracks the v5.5 feedback loop:

```text
search / wake source ids
  -> record_context_outcome
  -> RetrievalSignal(context_outcome)
  -> opt-in SearchBackend ranking metadata
```

## What It Proves

- `record_context_outcome` writes signal-only records.
- `weak_link_signals=True` lets search expose `context_outcome_score` and
  `ranking_explanation(kind=context_outcome)`.
- Confirmed truth count stays unchanged.

## What It Does Not Prove

- Broad answer-quality improvement.
- Token or cost savings.
- Production ranking gains.
- Default-on signal influence.

## Current Deterministic Gate

Run:

```bash
python -m pytest tests/loop_harness/test_context_outcome_loop.py -q --capture=no
```

Expected stdout includes:

```text
[loop_harness:context_outcome_loop]
```

The scenario reports:

- `context_outcome_signals`
- `used_score_positive`
- `misleading_score_negative`
- `explained_result_count`
- `truth_mutation_count`
