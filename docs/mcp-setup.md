# MCP Setup

`harness-mem quickstart` installs the `$hm` or `/hm` entry. It does not inspect
or change MCP connections. Connect `harness-mem-mcp` only when your Agent,
plugin, or MCP Router does not already provide harness-mem.

## Keep one connection

The unreleased development tree exposes 20 tools: the previous 19 plus
`inspect_sessions`. Published 0.9.28 also has 20 tools, but a different set:
it includes `dream_auto_tick` rather than `inspect_sessions`.
`dream_auto_tick` is no longer registered or exported: Hooks and maintenance
call the existing runtime directly. Explicit `dream_run` and `dream_ledger`
remain available. Reconnect the MCP client after upgrading to refresh discovery.
Custom callers of `dream_auto_tick` should stop scheduling it through MCP;
use the existing Hook lifecycle for automatic work or `dream_run` for an
explicit maintenance request. Do not move execution into the read-only debugger.

Automatic retrieval consumers now read `context_injection.memories`, not the
removed duplicate `search` or `answer_ready_context` projections. Retrieval and
source references remain in that injection for feedback. See
[the scheduler contract](autopilot-search-policy.md#runtime-scheduler-contract).

`finalize_session_distill` returns `answer_packet` only at the top level, no
longer duplicated inside `promotion`. Durable job records keep their packet
for Note generation and recovery. Chunk leases, source references, recovery
handles, completion status and cleanup results are unchanged.

Before adding anything, check the tools available in a new Agent task. If
harness-mem status, wake, or search tools are already available through a
Router or plugin, keep that connection and do not add a direct copy. Two active
copies can expose duplicate tools and may use different working directories.

## Session inspection and manual batches (unreleased)

These interfaces describe the working tree, not the published 0.9.28 package.
Completed `finalize_session_distill` responses now include `knowledge_changes`
(change, natural module, title and statement), ordinary `not_written` reasons,
and `unfinished_work`. These come from current SQLite rows after write/readback
verification, including replay; proposed drafts and the original conversation's
outcome are not the saved result. Manual batch reports use the same projection.
An explicit `search_memory(project_name=..., query="", scope="project")` lists
all current knowledge with modules. It does not read raw sources, create a job,
or start background processing. Nonempty search queries keep title/statement
results. The Agent renders these fields in the user's language through `hm`.

`inspect_sessions` requires an absolute `project_root` and supports:

- `action="inventory"`: read project ownership, source readability and processing
  state without importing sources, creating jobs, writing memory or starting
  background work. With `batch_id`, read the existing frozen batch's progress.
- `action="source"`: pass a returned `session` reference and follow `next_offset`
  with `offset`/`page_chars` to read the complete permitted source revision.
  Respect capture exclusions and private-content redaction.
- `action="overview"`: provide selected `sessions`, source-page `coverage`
  (reference, content digest and ranges), and Agent-proposed `topics` with source
  locations. Partial coverage remains partial; multiple themes and unclassified
  sessions are valid. Themes do not replace per-point extraction or verification.

For explicit manual processing, call `prepare_session_distill` with
`project_root` and `batch_sessions` containing the returned source references.
Resume using `batch_id` without replacing the selection. The manifest freezes
project/root, source revisions, runtime fingerprint and prior-completed
references, and retains job bindings and unresolved failures. It is temporary
processing state under `manual-batches`, not knowledge history.

The current Agent reads and submits chunks and finalizes each prepared job
through the existing distill tools, then prepares the next job with the same
`batch_id`. This does not require background processing or its selected CLI.
Use `retry_failures=true` with an existing active batch only for an explicit
retry; it does not resume a stopped batch. Changed runtime or failed completion
verification must not be treated as successful resume. Reports distinguish
current-run knowledge changes from previously completed work. Batch processing
retains sources; it does not authorize automatic deletion.

Cursor SQLite support is limited to the layouts covered by the isolated native
store fixtures, not every live Cursor database format. The original 12 outcome
contracts now include a thirteenth `manual_session_batch` probe in the working tree; a fixture pass
or a configured probe is not proof of live background Hook success. The
[roadmap](roadmap.md) retains the separate Hermes preflight blocker.

## Direct connection

The server command is:

```bash
harness-mem-mcp
```

Use the Agent's normal MCP settings to add a project-scoped server:

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

Replace `cursor` with the current Agent: `codex`, `claude-code`, `cursor`,
`grok`, `hermes`, `opencode`, or `antigravity`. Use that Agent's workspace
variable syntax. If it cannot set `cwd`, set `HARNESS_MEM_PROJECT_ROOT` to the
absolute project path instead.

`harness-mem-mcp` is installed with the Python package. If the Agent cannot
find it, use the absolute path reported by `where harness-mem-mcp` on Windows
or `which harness-mem-mcp` on macOS/Linux.

## MCP Router

Register one `harness-mem-mcp` server in the Router, set the current workspace
as its working directory, and grant the active Agent access. Do not also enable
a direct harness-mem entry for the same Agent.

The Router chooses the visible tool prefix. A Router named `mcp_router` may
expose `mcp__mcp_router__get_project_status`; a direct server named
`harness_mem` may expose `mcp__harness_mem__get_project_status`. These are the
same logical tool. Users should use `$hm` or `/hm`, not type these names.

## Restart and verify

After adding or changing the connection:

1. Restart the harness-mem server in the Agent or Router.
2. Start a new Agent task; existing tasks keep the tool snapshot they started with.
3. Ask: `Use harness-mem to check this project.`

Successful verification must identify the current project and current Agent.
If Codex reports that project Hooks need review, open **Settings > Hooks**,
review them, and start another task.

## More detail

- [Quickstart](quickstart.md) covers package and `$hm`/`/hm` installation.
- [Host and Hook support](ide-hook-adapter-matrix.md) lists verified host
  behavior and repair commands.
- [Background memory](background-memory.md) explains the optional automatic
  processing setting.
- [Quickstart privacy and repair](quickstart.md#advanced-and-repair) explains
  local data and deletion behavior.
