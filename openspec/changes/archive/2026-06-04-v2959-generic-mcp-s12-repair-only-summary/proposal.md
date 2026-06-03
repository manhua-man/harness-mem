## Why

The packet already had generic MCP evidence for running review surfaces, but it
still lacked a live entry proving the post-distill summary itself no longer
pushes `/hm:review` as the default next step.

## What Changes

- Add a live generic MCP `auto_review_candidates(apply=true)` summary entry.
- Record that the summary payload does not contain `/hm:review`.
- Add a focused regression guard.
- Update release writeback for `v2.9.59`.

## Impact

- The packet now captures the repair-only boundary as live evidence.
- The repo still does not overclaim a full UI-level natural-language validation
  across every client.
