# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
harness-mem-mcp
```

For a project-scoped MCP entry, set the server's working directory to the
workspace and pass the owning client in `HARNESS_MEM_CLIENT`. On its first
`initialize` request, a recognized client automatically records the project
profile, makes it active, and installs its hook suite without overwriting
existing hook files.

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

`harness-mem-mcp` is installed alongside `harness-mem` and therefore starts
the server from the same Python environment as the installed package. Verify
the command in a terminal before adding it to the IDE. If the IDE does not
inherit that terminal `PATH`, use the absolute path reported by `where
harness-mem-mcp` (Windows) or `which harness-mem-mcp` (macOS/Linux) as the
`command` value.

Use the client-specific syntax for the workspace variable: `cursor`,
`claude-code`, `grok`, `codex`, `hermes`, `opencode`, and `antigravity` are recognized. Where
a client cannot set `cwd`, set `HARNESS_MEM_PROJECT_ROOT` to the absolute
workspace path instead. The environment value belongs in the MCP server entry,
not only the hook command, so initialization sees the correct host identity.

The server has one public memory surface. It exposes the normal Agent workflow:
status, wake/search, session distill, candidate suggestion, explicit
candidate review, and dream as the default audited maintenance capability.
Historical profile values are ignored.
The `wake` output leads with a recent project-scoped context index. It is a
derived view of transcript observations and does not promote them to confirmed
truth; stable truth and active handoffs remain separate sections.
`get_project_status` includes `integration_health.summary` for a concise check
of project root, configured host, installed hooks, transcript observations, and
pending distill work. Missing `HARNESS_MEM_CLIENT` is reported as `unknown`.
For Codex, `hooks=review_required` means the project manifest was installed but
the current Hook configuration has not yet executed. Open **Codex Settings >
Hooks**, trust the project hooks, and start a new task. The status changes to
`ok` only after the matching `SessionStart` Hook completes; changing the Hook
manifest invalidates the old execution receipt.

Invocation paths are Agent MCP calls, `/hm:*` commands, installed skills, and
explicit IDE hooks. Session-start/PreInvocation hooks inject wake context; runtime task hooks
call `autopilot_search_tick`, which decides whether to run bounded
`search_memory`; save-point or session-end hooks sync evidence and queue
Agent-led distillation.

`autopilot_search_tick` is the event-level scheduler. PI
`transformContext` / `tool_result` / `prepareNextTurn`, Claude Code
`PostToolUse`, and Cursor after-agent hooks should map their native event
payloads into that tool. It searches only for concrete uncertainty, conflict,
tool failure, durable-claim grounding, or long-horizon task switches; it is not
a second `wake`.

`prepare_session_distill` syncs native transcript revisions and claims their
ordered chunks. Chunks are never shortened to fit one MCP response; long
sessions continue over multiple Agent calls with leases and durable
checkpoints. After all chunks complete, the Agent receives the ordered chunk
results and must submit a structured end-of-session review. Candidate writes
bound to that job use stable IDs so retries do not duplicate memory.
`finalize_session_distill` applies the shared low-risk policy, completes that
one explicit job, and runs Dream. Lower-level sync and chunk tools are internal
Agent workflow, not user commands. Ambiguous or high-risk items remain in
`/hm:review`. Operator
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
actions, including dream. Project-scoped MCP initialization installs the
matching IDE hooks automatically. If hooks are missing, the next MCP
initialization repairs the project-local installation without overwriting
existing files.

## Generic MCP Client

Add a project-scoped server entry that runs from the workspace:

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

Replace `cursor` with the actual MCP host. For an unrecognized generic client,
omit the client variable; regular MCP tools still work, while automatic hook
installation is skipped.

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
