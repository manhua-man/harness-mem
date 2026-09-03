---
name: harness-mem
description: Use harness-mem as a local-first memory runtime for the current project. Trigger when the user asks to remember prior work, resume a project, search old agent sessions, distill recent agent sessions, create durable project rules, or explain what the project currently knows.
metadata:
  wireFormatVersion: hm-wire-v3.5
---

# harness-mem

## What This Skill Does

Use this skill to operate the local `harness-mem` runtime from a project workspace.

Treat the project as real production context:

- Prefer MCP tools (`get_project_status`, `wake`, `search_memory`, `timeline`) before guessing from memory.
- Use `prepare_session_distill` for stale project state; it syncs immutable transcript revisions and claims complete ordered chunks.
- Follow the self-contained distill contract in this installed skill when the
  user asks `$hm` or `/hm` to remember a session; runtime behavior remains in
  public `harness-mem` MCP tools.
- Distilled memory is governed automatically. Low-risk items may become readable memory; review is the post-hoc audit and correction surface.
- Use `govern_memory(action="suggest")`, `list_candidates`, and
  `govern_memory(action="decide")` for stable facts or rules the user explicitly
  wants remembered.
- Confirmed truth can be maintained automatically, but it must not be silently overwritten; durable changes go through candidate / review / supersede / ledger.
- Cross-project skills can be read as procedural memory hints, but lifecycle management is outside the public memory MCP surface.
- Keep the default surface to one entry: `$hm` in Codex and `/hm` elsewhere.
  Do not create or recommend action-specific entries.
- Retain original session sources by default. Delete only after an operator
  explicitly enables `distill.delete_source_after_complete=true` with
  `--confirm`; supported standalone sources must still pass quiet/CAS/hash
  checks, and the actual cleanup status must be reported.

Resolve MCP calls from the current task's tool inventory by logical tool name.
Codex behind MCP Router normally exposes `mcp__mcp_router__*`; a direct server
normally exposes `mcp__harness_mem__*`; some clients expose bare tool names.
Do not treat one server prefix as universal, and do not report MCP unavailable
until the active Router/direct namespace has been checked.

## Mental Model

- `get_project_status`: checks active project and current memory counts. Always pass
  `project_root=<current workspace root>` and `host_client=<current IDE/Agent>` so
  a global MCP Router can idempotently install the correct native hooks.
- `prepare_session_distill`: syncs native revisions. Daily `evidence_mode="semantic", detail_level="compact"` hash-verifies/checkpoints every raw chunk and returns an all-indexed manifest; `budget_tokens` is a configurable soft target for the complete Agent-visible response (3000 is only the default), and `response_budget` reports actual cost/expansion. Selected semantic windows and raw proof are separate drilldowns. `detail_level="full"` and `evidence_mode="raw"` are explicit audit paths.
- `submit_distill_chunk`: checkpoints one completely read chunk so interrupted work can resume without skipping content.
- `finalize_session_distill`: verifies revision currency, complete chunk coverage, and semantic promotion gates, then reviews only the current explicit job's candidates. It never starts a second unattended Dream run.
- `auto_review_candidates`: project-level audit/maintenance tool, not the lossless session finalization stage.
- `search_memory` / `timeline`: finds prior decisions, errors, discussions, and event history.
- `govern_memory` / `list_candidates`: create and review durable memory candidates through one public write boundary.
- Processed-source cleanup is controlled only by the persistent
  `distill.delete_source_after_complete` policy and preserves sanitized durable
  truth. Explicit privacy erasure uses `harness-mem maintenance erase`, starts
  with preview, and removes the complete internal closure plus eligible native
  session sources only after `--apply`.

## Everyday Workflow

From the repository root, the user-facing path is IDE command / skill / natural-language agent instruction, not manual CLI. If the client has no slash command surface (for example Cursor through a router), tell the user the natural-language prompt to give the agent instead of listing terminal commands or MCP tool names.

For status and wake-up:

1. Call `get_project_status(project_root=<current workspace root>, host_client=<current IDE/Agent>)`
   to resolve the project, create its profile, and idempotently bootstrap the native hooks.
2. When the project is ready, call `wake(project_name=<project>)` instead of manually stitching low-level read tools.
3. If the user explicitly wants procedural hints, call `wake(project_name=<project>, include_skill_hints=true)`, and only call `get_skill(skill_id)` if they ask to expand a specific hint.
4. Keep wake read-only. Do not claim a queued job, consume a maintenance offer,
   call a provider, or mutate knowledge. Hook-created work is processed by an
   authorized Dream run; immediate user-requested work uses explicit distill in
   the active host.
5. Summarize the usable context directly. If the user wants another memory
   action, tell them to use `$hm` in Codex or `/hm` elsewhere and say what they
   want in ordinary language. Do not make them choose an internal action name.

If the project has new sessions:

1. Call `prepare_session_distill(project_name=<project>, client="auto", scope="project", project_root=<current project root>, evidence_mode="semantic", detail_level="compact", budget_tokens=<configured or user target>)`.
2. Read the complete indexed manifest in order. Select likely candidate windows with `drilldown_exchange_indexes=[...]`, then obtain candidate-grade raw proof with `drilldown_query="<term>"` or known `drilldown_chunk_indexes=[...]`. Runtime has already hash-verified and checkpointed every raw chunk; use `detail_level="full"` or `evidence_mode="raw"` only for explicit audit or runtime fallback.
3. Review the complete indexed manifest plus selected semantic windows and raw
   proof (or raw checkpoint results), then apply this skill's candidate
   admission and evidence checks.
4. Write pending candidates only for admitted items through
   `govern_memory(action="suggest", arguments={kind: "memory|rule|relation", ...})`,
   passing the current `distill_job_id` in `arguments`. For external claims,
   evidence may be attached after candidate creation, but must be present before
   a `govern_memory(action="decide", arguments={decision: "confirm", ...})` call.
5. Call `finalize_session_distill` with the complete semantic review. Report its
   actual runtime disposition, including partial completion, handoff, or
   retryable failure when present, plus retained/deleted/failure source status;
   keep decision counts and internal IDs in explicit audit drilldown.

The explicit user distill path above may sync new sessions and honor the user's
requested count, with a hard maximum of three sequential jobs per invocation.
A wake maintenance offer is different: it targets the ordered exact offered
ids, sets `run_ingest=false`, and obeys its bounded `process_limit` (default two).

Resolve evidence gaps from the transcript, repository, tests, and current docs.
Ask the user only when the remaining uncertainty is their preference, intent,
or product direction; do not create a separate question-routing workflow.

When looking for prior work:

Call MCP `search_memory(project_name=<project>, query=<query>, mode="auto")`, then use `timeline` or `get_observations` for provenance.

If the user explicitly wants cross-project borrowing, call
`search_memory(project_name=<project>, query=<query>, mode="auto", scope="all")`
and present results grouped by `project_name`, keeping current-project hits
separate from other projects worth borrowing from.

For opt-in maintenance:

Use maintenance Slash entries only when the user explicitly asks for session
artifact cleanup. KB and PRD semantics are normal memory candidates; this
plugin does not expose a separate KB audit or PRD sync product surface.

At closeout, run the repository's normal checks, use
`govern_memory(action="handoff")` for resumable work, and finalize memory only
through `finalize_session_distill`. Do not create a parallel journal or spec truth store.

When the user states a durable project rule:

Call MCP `govern_memory(action="suggest")`, then show `list_candidates`; only call `govern_memory(action="decide")` after the user explicitly decides.

## CLI Fallback

CLI remains the operator interface for install checks, local diagnostics,
integration sync, and explicit cleanup previews. Do not present CLI commands as
the normal user workflow when MCP tools are available. `purge` is a soft
maintenance delete; `erase` is privacy deletion and defaults to preview. Only
run either with `--apply` after the user approves the exact scope.

## MCP Use

The plugin exposes the MCP server config. MCP is the runtime tool interface used by an agent to call status, distill, search, timeline, and review tools without asking the user to run every command manually.
