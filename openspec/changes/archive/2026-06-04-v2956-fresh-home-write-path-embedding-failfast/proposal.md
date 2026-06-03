## Why

Live stdio MCP runs on the current machine showed that `suggest_memory_entry`
could still stall in a fresh isolated home even after the earlier write-path
timeout guard landed. The remaining gap was not a cached-model encode hang; it
was the first-time Hugging Face model load/download triggered by write-path
embedding persistence.

Interactive candidate writes should not perform a cold model download just to
produce a vec row.

## What Changes

- Detect whether the configured embedding model already has a local cache
  snapshot.
- If the model is cold-cache, skip write-path vec generation and log a warning
  instead of attempting a first-time download on the interactive write path.
- Keep the existing timeout/circuit-breaker path for cached-but-hung
  encode/import failures.
- Record fresh-home live MCP evidence in `docs/v2-user-test-packet.md`.
- Update release writeback for `v2.9.56`.

## Impact

- Fresh isolated homes no longer need `HARNESS_MEM_DISABLE_EMBEDDINGS=1` just
  to keep minimal interactive writes responsive.
- Cold-cache write paths still do not guarantee a vec row; they prioritize
  responsiveness and correctness of the structured write.
- The packet now reflects the current runtime truth instead of the older
  workaround-only state.
