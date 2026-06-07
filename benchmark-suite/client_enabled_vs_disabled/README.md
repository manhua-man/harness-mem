# Client Enabled vs Disabled

First-pass prompt pack for paired real-client continuation benchmarks.

Run every task twice:

- `enabled`: the agent may use harness-mem read surfaces such as `wake`,
  `search_memory`, `timeline`, and `get_observations`.
- `disabled`: the agent must not use harness-mem read or write surfaces.

The prompts are intentionally task-level, not implementation-level. They ask the
client to recover prior project truth, then produce a small answer that can be
judged with the checklist before the run starts.

## Files

- `prompts.json`: stable T1-T5 prompt definitions.
- `acceptance_checklist.md`: binary pass/fail rubric for each task and condition.

## Run Rule

Keep the client, model, workspace, repo state, and prompt text fixed across each
enabled/disabled pair. Record every result under `benchmark-suite/artifacts/`
with one result JSON per task/condition and a transcript for each run.
