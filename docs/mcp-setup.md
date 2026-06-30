# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
python -m harness_mem.mcp.server
```

The server has one public memory surface. It exposes the normal Agent workflow:
status, wake/search, session ingest/distill, candidate suggestion, explicit
candidate review, and dream as the default audited maintenance capability.
Historical profile values are ignored.

Invocation paths are Agent MCP calls, `/hm:*` commands, installed skills, and
explicit IDE hooks. Session-start hooks inject wake context; runtime task hooks
call `autopilot_search_tick`, which decides whether to run bounded
`search_memory`; save-point or session-end hooks can run distill and dream
maintenance.

`autopilot_search_tick` is the event-level scheduler. PI
`transformContext` / `tool_result` / `prepareNextTurn`, Claude Code
`PostToolUse`, and Cursor after-agent hooks should map their native event
payloads into that tool. It searches only for concrete uncertainty, conflict,
tool failure, durable-claim grounding, or long-horizon task switches; it is not
a second `wake`.

`prepare_session_distill` packages recent project observations into an evidence
packet; it does not synthesize candidate truth on its own. The candidate layer
is still written by the session-distill / suggest_* path, and
`auto_review_candidates` then applies the shared low-risk policy and records
audit events. Ambiguous or high-risk items remain in `/hm:review`. Operator
maintenance and skill lifecycle management are not public MCP tools.
Read-only procedural hints can be searched from memory context, but procedural
skill lifecycle management is outside this public memory surface.

## Operator Maintenance

Metabolism and reflection jobs are internal background governance mechanisms,
similar to an indexer, compaction worker, repair worker, or GC. Product-facing
flows should describe the outcome instead: memory is automatically organized,
deduplicated, expired, repaired, and consolidated.

MCP has no maintenance profile. The public MCP surface does not list these
internals, does not report hidden maintenance counts, and treats direct calls
to maintenance-only tools as unknown. Operators should diagnose local state
through `harness-mem doctor` and explicit CLI maintenance commands.

## Claude Code

On Windows:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

The plugin also includes the Daily `/hm:*` command files for common memory
actions, including dream. For IDE hooks, prefer the one-shot suite installer:
`harness-mem integration install-hook-suite --client cursor` or
`--client claude-code`.

## Generic MCP Client

Add a server entry that runs:

```json
{
  "command": "python",
  "args": ["-m", "harness_mem.mcp.server"]
}
```

After registration, ask the Agent to:

```text
Use harness-mem to wake this project.
Search harness-mem for the relevant project decision.
```

## Notes

- The CLI is mainly for setup, doctor checks, and maintenance.
- CLI import/purge are maintenance-only commands:
  `harness-mem maintenance import` and `harness-mem maintenance purge`; both
  default to dry-run.
- Other CLI maintenance actions stay limited to operator repair and audit tasks
  such as index rebuilds, storage migration/export, and state audit.
- Skill lifecycle governance is outside the public memory MCP and CLI product
  surface.
- Daily use should happen through the Agent client and MCP tools.
- `distill` creates candidates first and previews review decisions; review
  decides what becomes confirmed memory.
