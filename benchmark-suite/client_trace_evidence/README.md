# Client Trace Evidence

Benchmark design for user-visible client transcript evidence.

Status: ready-to-run design. A result only supports the exact client, prompt,
workspace, and artifact bundle that was recorded.

## Goal

Capture user-visible evidence that the runtime behaves correctly in actual
clients, without converting near-neighbor traces into stronger claims.

## Run Shape

Each task is run once in the `trace` condition for a named client.

Required controls:

- exact client family and version if visible
- model if visible
- workspace path
- repo state
- prompt text
- transcript
- tool calls if visible

## Files

- `prompts.json`: trace evidence tasks.
- `acceptance_checklist.md`: pass/fail rubric.
