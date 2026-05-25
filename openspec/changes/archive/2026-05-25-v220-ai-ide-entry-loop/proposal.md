## Why

v2.1 cleaned up the product surface: daily CLI commands and REST API are no longer
the user path, and MCP is the hidden transport behind IDE commands, Skills, and
agent workflows. The remaining risk is practical: users can still be pushed back
to CLI flags or raw MCP tool names if the command/Skill/client loop is not
specified and tested as one golden path.

v2.2 should make the AI IDE entry loop dispatchable and testable before deeper
Memory Metabolism work creates more candidate volume.

## What Changes

- Define a canonical user-visible workflow for `/hm:distill`, `/hm:wake`,
  `/hm:search`, `/hm:review`, and natural-language equivalents.
- Make project resolution, distill closed-loop behavior, failure messages, and
  final summary shape explicit.
- Turn the v2 user test packet into a v2.2 cross-client matrix for Claude Code,
  Codex, Cursor, and generic MCP clients.
- Add stale-surface checks so removed daily CLI commands do not reappear in
  README / AGENTS / plugin command instructions.
- Harden auto-review UX so low-risk candidates are handled by the agent and only
  high-risk leftovers reach the user.

## Impact

- Orchestrator mode has a concrete `tasks.md` to dispatch from.
- Users interact through IDE-native commands or natural language, not terminal
  command lists.
- MCP remains an implementation detail unless a developer is debugging raw tool
  integration.
- v2.3/v2.4 metabolism work starts from a stable user loop instead of dumping
  more candidates into a brittle review surface.

