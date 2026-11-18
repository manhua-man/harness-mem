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

<a id="session-inspection-and-manual-batches-unreleased"></a>

## Session inspection and memory review (unreleased)

These interfaces describe the working tree, not the published 0.9.28 package.

For a question that depends on preceding task context, `search_memory` accepts
optional `task_context` separately from `query`. Supply the complete necessary
background, conditions and exclusions. It remains a search input, not proof of
user approval. Reuse the exact text when opening a candidate or following its
continuation; `reuse_arguments` names fields to copy from the original request.
The cursor contains hashes rather than the context text and rejects a different
context, store or retrieval/model version. Every selected full read still returns
the complete stored entry, including report attribution and final conditions.

Manual searches with `task_context` and `detail="auto"` compare the actual token
cost of a complete entry object with its preview-plus-cursor card. When the
complete form is cheaper, it is returned directly as `statement`; the page may
contain complete statements and previews together, marked `detail="mixed"`.
`mixed` is an output marker, not an input detail value. Only `statement` contains
the full stored content; reuse it without another full-read request. Only a
preview needs its strict `read_cursor`. Relevance remains unassessed in both
forms, and the entire final response stays under the same page budget.
Explicit `detail="candidates"` and automatic Hook/scheduler paths keep previews
only. Search-hit feedback counts only complete entries actually returned.

The optional `semantic-onnx` dependency extra supports an offline BGE small
Chinese candidate channel over current knowledge, without a model service or
legacy memory-table index. An operator must explicitly point the process at
`HARNESS_MEM_CURRENT_SEMANTIC_MODEL_DIR`, containing `model_int8.onnx`,
`tokenizer.json`, `config.json` and `tokenizer_config.json` from the same pinned
artifact. No model is downloaded or bundled automatically.
`HARNESS_MEM_DISABLE_EMBEDDINGS` still takes precedence. Missing dependencies,
unconfigured/corrupt files or encoding failure leave lexical retrieval available
and context-aware calls return an explicit semantic-unavailable notice. With
semantic discovery available, context-aware calls retain its order and exact
literal readback priority. Ordinary natural questions also use the configured
model for additional candidates above a similarity floor. Without the model,
long questions can match multiple distinct shared fragments when their phrases
have no direct match. Short literal lookups still take the lexical path.
Candidate similarity never establishes relevance or an answer; the current Agent
must read and assess the selected complete entries. Development/acceptance status
is recorded in [the current plan](roadmap.md#current-iteration-plan).

Completed `finalize_session_distill` responses now include `knowledge_changes`
(change, natural module, title and statement), ordinary `not_written` reasons,
and `unfinished_work`. These come from current SQLite rows after write/readback
verification, including replay; proposed drafts and the original conversation's
outcome are not the saved result. Manual batch reports use the same projection.
An explicit `search_memory(project_name=..., query="", scope="project")` lists
all current knowledge with modules. It does not read raw sources, create a job,
or start background processing. Nonempty search queries keep title/statement
results. The Agent renders these fields in the user's language through `hm`.

Evidence can come from a different local maintenance directory. In the user
configuration `~/.harness-mem/config.toml`, list the directories you want the
runtime to read as repository evidence. Example Windows configuration:

```toml
[evidence]
repository_roots = ["F:/project-reference/docs"]
```

Use an absolute `repository` locator under a configured directory and submit
the SHA-256 of the checked file. The runtime binds the file to the original
knowledge owner and rechecks scope and bytes when it reopens the citation.
Project configuration cannot grant this permission. Project-local references
still use their existing relative paths. Ordinary search displays the knowledge
statement without the raw citation or source text.

Manual `finalize_session_distill` may return `source_conditions_need_review`
before staging any write. It shows explicit condition clauses from the session
and checked text files that appear related to a writing point. Retain relevant
conditions in the statement and `review.conditions`. Explain exclusions for
session-only, superseded or out-of-scope material with `condition_exclusions`,
using the returned IDs. The organizer still checks implicit conditions,
applicability and conflicts.

`inspect_sessions` defaults to device scope; absolute `project_root` is an optional explicit source filter. It supports:

- `action="inventory"`: read project ownership, source readability and processing
  state without importing sources, creating jobs, writing memory or starting
  background work. Inventory also returns existing batches, persisted progress,
  directly callable inspect/resume/explicit-continue arguments and none/unique/ambiguous
  `batch_continuation`. With `batch_id`, read that frozen batch's progress; inspection
  never clears a pause.
- `action="source"`: pass a returned `session` reference and follow `next_offset`
  with `offset`/`page_chars` to read the complete permitted source revision.
  Respect capture exclusions and private-content redaction.
- `action="overview"`: provide selected `sessions`, source-page `coverage`
  (reference, content digest and ranges), and Agent-proposed `topics` with source
  locations. Partial coverage remains partial; multiple themes and unclassified
  sessions are valid. Themes do not replace per-point extraction or verification.

Daily session intake and organization belong to the Hook and automatic worker.
The public `prepare_session_distill` entry also accepts exact `target_knowledge`
for correction, an existing `distill_job_id` for review, or explicit history
selection via `batch_sessions`. `batch_id` resumes that same selection;
`pause=true` stops progress, `continue_batch=true` requires an explicit request
to continue a user pause, and `retry_failures=true` retries only eligible active
failures. Source/revision/ownership failures retain their stopped state.

The Agent follows references returned by read-only inventory; users describe
scope and do not copy internal IDs. Manifests under `manual-batches` are temporary
processing state. They neither authorize source deletion nor permit changing a
frozen scope or reporting unfinished work as complete. Current-Agent processing
needs no background CLI authorization or task budget. New writes require the
structured `final_scope_judgment` object at finalize (top level or semantic_review)
or govern decide arguments, complete source reopening, target-version checks,
canonical commit and normal readback. See the [judgment contract and complete
example](memory-write-convergence-20261020.md#13-公开最终语义判断合同与调用例).

Background task budgets cover native executor invocations dispatched by this runtime across source processing, Dream slices and retries under one maintenance task identity. Defaults are 64 invocations, 3,600 cumulative native seconds, 2,000,000 input tokens and 128,000 output tokens. Actual terminal usage is accumulated and checked before subsequent dispatch; the final invocation may cross a token threshold and may contain multiple model responses. Unknown usage blocks later invocations. These thresholds do not cap returned context, total user wait or the current Agent conversation. An explicit `task_model_budget.host_max_output_tokens` requests strict native bounds; unsupported or unproved bounds refuse before transport. Ordinary background execution does not require this optional hard cap. Local installation and readiness have fresh receipts; natural semantic acceptance remains pending.

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
