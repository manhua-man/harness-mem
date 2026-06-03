## Why

The packet already had several generic MCP scenario entries, but it still
lacked a live run showing that truth confirmed in one session becomes visible
to a later session. That left `S10` without any real generic MCP evidence.

## What Changes

- Add a live two-session generic MCP run:
  - writer session creates and confirms a memory entry
  - reader session wakes the same project and reads it back under L1
- Record the result in `docs/v2-user-test-packet.md`
- Add a focused regression guard
- Update release writeback for `v2.9.58`

## Impact

- Generic MCP coverage now includes cross-session confirmed-truth visibility.
- The repo still avoids overstating this as a full UI-level cross-client pair.
