## Why

`docs/v2-user-test-packet.md` still said non-Claude clients had not been run at
all, but the current machine can already execute a minimal Codex MCP path:

- `set_active_project`
- empty-project `wake`
- `suggest_memory_entry`

That made the packet weaker than the live evidence while still not being strong
enough to claim the full cross-client matrix was complete.

## What Changes

- Add a run-log entry documenting the current-machine Codex MCP smoke.
- Update `roadmap-v22x.md` and `roadmap-status.md` to distinguish:
  - at least one non-Claude smoke exists
  - the full manual matrix is still open
- Keep a focused regression test guarding that wording.
- Update release writeback for `v2.9.55`.

## Impact

- The packet no longer understates current non-Claude evidence.
- The repo still avoids overstating the manual release gate as complete.
- Packet, roadmap, and status docs stay aligned with the actual validation state.
