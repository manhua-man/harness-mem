---
name: harness-mem
description: Use harness-mem as a local-first memory runtime for the current project. Trigger when the user asks to remember prior work, resume a project, search old agent sessions, distill recent agent sessions, create durable project rules, or explain what the project currently knows.
wireFormatVersion: hm-wire-v3.5
---

# harness-mem

## What This Skill Does

Use this skill to operate the local `harness-mem` runtime from a project workspace.

Treat the project as real production context:

- Prefer MCP tools (`get_project_status`, `wake`, `search_memory`, `timeline`) before guessing from memory.
- Use `prepare_session_distill` for stale project state; it syncs immutable transcript revisions and claims complete ordered chunks.
- Use repo-local `code/tools/hm-distill/SKILL.md` as the instruction-only Agent playbook; all runtime behavior remains in `harness_mem` MCP tools.
- Distilled memory is governed automatically. Low-risk items may become readable memory; review is the post-hoc audit and correction surface.
- Use `govern_memory(action="suggest")`, `list_candidates`, and
  `govern_memory(action="decide")` for stable facts or rules the user explicitly
  wants remembered.
- Confirmed truth can be maintained automatically, but it must not be silently overwritten; durable changes go through candidate / review / supersede / ledger.
- Cross-project skills can be read as procedural memory hints, but lifecycle management is outside the public memory MCP surface.
- Keep the default surface to Daily commands: wake, search, distill, review, and dream. Artifact maintenance commands are opt-in.
- Successful distill attempts receipt-first source cleanup by default. Delete
  only supported standalone sources that pass quiet/CAS/hash checks, preserve
  shared or unsafe containers, and report the actual cleanup status.
- When the user asks to retain original sessions, map it to
  `harness-mem config set distill.delete_source_after_complete false --scope project`.
  Re-enabling an explicitly disabled policy requires `--confirm`.

Resolve MCP calls from the current task's tool inventory by logical tool name.
Codex behind MCP Router normally exposes `mcp__mcp_router__*`; a direct server
normally exposes `mcp__harness_mem__*`; some clients expose bare tool names.
Do not treat one server prefix as universal, and do not report MCP unavailable
until the active Router/direct namespace has been checked.

## Mental Model

- `get_project_status`: checks active project and current memory counts. Always pass
  `project_root=<current workspace root>` and `host_client=<current IDE/Agent>` so
  a global MCP Router can idempotently install the correct native hooks.
- `ingest_sessions`: low-level transcript sync for `/hm:distill` internals and diagnostics; do not present it as the user workflow.
- `prepare_session_distill`: syncs native revisions. Daily `evidence_mode="semantic", detail_level="compact"` hash-verifies/checkpoints every raw chunk and returns an all-indexed manifest; `budget_tokens` is a configurable soft target for the complete Agent-visible response (3000 is only the default), and `response_budget` reports actual cost/expansion. Selected semantic windows and raw proof are separate drilldowns. `detail_level="full"` and `evidence_mode="raw"` are explicit audit paths.
- `submit_distill_chunk`: checkpoints one completely read chunk so interrupted work can resume without skipping content.
- `code/tools/hm-distill/SKILL.md`: instruction-only Agent playbook for final review and candidate drafting.
- `finalize_session_distill`: verifies revision currency, complete chunk coverage, and semantic promotion gates, then reviews only the current job's candidates and runs Dream.
- `auto_review_candidates`: project-level audit/maintenance tool, not the lossless session finalization stage.
- `search_memory` / `timeline`: finds prior decisions, errors, discussions, and event history.
- `govern_memory` / `list_candidates`: create and review durable memory candidates through one public write boundary.
- Processed-source cleanup is controlled only by the persistent
  `distill.delete_source_after_complete` policy and preserves sanitized durable
  truth. Explicit privacy erasure uses `harness-mem maintenance erase`, starts
  with preview, and removes the complete internal closure plus eligible native
  session sources only after `--apply`.

## Daily Workflow

From the repository root, the user-facing path is IDE command / skill / natural-language agent instruction, not manual CLI. If the client has no slash command surface (for example Cursor through a router), tell the user the natural-language prompt to give the agent instead of listing terminal commands or MCP tool names.

For status and wake-up:

1. Call `get_project_status(project_root=<current workspace root>, host_client=<current IDE/Agent>)`
   to resolve the project, create its profile, and idempotently bootstrap the native hooks.
2. When the project is ready, call `wake(project_name=<project>)` instead of manually stitching low-level read tools.
3. If the user explicitly wants procedural hints, call `wake(project_name=<project>, include_skill_hints=true)`, and only call `get_skill(skill_id)` if they ask to expand a specific hint.
4. If `wake.distill_maintenance.agent_execution_required=true`, process the
   ordered exact offered job ids sequentially up to `process_limit`, using the
   returned prepare contract (`run_ingest=false`, semantic/compact, configured
   response target). Finalize or defer each owned job independently; skip a
   busy lease without deferring it. Do not expose the private maintenance block or ask the
   user to run distill for parked history.
5. Summarize the usable context and suggest the next IDE-native action:
   - Claude Code: `/hm:distill`, `/hm:review`, or `/hm:wake`.
   - Cursor / Antigravity / opencode / Hermes / generic AI IDE: "用 harness-mem 唤醒当前项目" or "用 harness-mem 整理最近 N 个 session".
   - Do not present terminal commands as the normal answer when MCP tools are available.

If the project has new sessions:

1. Call `prepare_session_distill(project_name=<project>, client="auto", scope="project", project_root=<current project root>, evidence_mode="semantic", detail_level="compact", budget_tokens=<configured or user target>)`.
2. Read the complete indexed manifest in order. Select likely candidate windows with `drilldown_exchange_indexes=[...]`, then obtain candidate-grade raw proof with `drilldown_query="<term>"` or known `drilldown_chunk_indexes=[...]`. Runtime has already hash-verified and checkpointed every raw chunk; use `detail_level="full"` or `evidence_mode="raw"` only for explicit audit or runtime fallback.
3. Activate repo-local `code/tools/hm-distill/SKILL.md`: review the complete indexed manifest plus selected semantic windows and raw proof (or raw checkpoint results), then apply its inline candidate admission check and `references/distillation-rules.md`.
4. Write pending candidates only for admitted items through
   `govern_memory(action="suggest", arguments={kind: "memory|rule|relation", ...})`,
   passing the current `distill_job_id` in `arguments`. For external claims,
   evidence may be attached after candidate creation, but must be present before
   a `govern_memory(action="decide", arguments={decision: "confirm", ...})` call.
5. Call `finalize_session_distill` with the complete semantic review. Report its
   `promoted`/`no_candidate` disposition and retained/deleted/failure source
   status concisely; keep decision counts and candidate IDs in audit drilldown.

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
