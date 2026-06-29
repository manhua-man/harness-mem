---
name: harness-mem
description: Use harness-mem as a local-first memory runtime for the current project. Trigger when the user asks to remember prior work, resume a project, search old agent sessions, ingest recent agent sessions, create durable project rules, or explain what the project currently knows.
wireFormatVersion: hm-wire-v3.5
---

# harness-mem

## What This Skill Does

Use this skill to operate the local `harness-mem` runtime from a project workspace.

Treat the project as real production context:

- Prefer MCP tools (`get_project_status`, `wake`, `search_memory`, `timeline`) before guessing from memory.
- Ingest recent sessions through MCP `ingest_sessions` when the project state may be stale.
- Use repo-local `tools/session-distill` for user-triggered distillation; do not use the removed heuristic distill path.
- Distilled memory is a draft signal. Review it before treating it as durable truth.
- Use `suggest_*`, `list_candidates`, and `confirm_*` / `reject_*` for stable rules the user explicitly wants remembered.
- Confirmed truth can be maintained automatically, but it must not be silently overwritten; durable changes go through candidate / review / supersede / ledger.
- Cross-project skills can be read as procedural memory hints, but lifecycle management is outside the public memory MCP surface.
- Keep the default surface to Daily commands: wake, search, distill, review, and dream. Artifact maintenance commands are opt-in.
- Do not delete raw agent session files unless the user explicitly asks for raw-file cleanup through an opt-in maintenance entry.

In Claude Code, prefer the no-hyphen MCP alias names such as
`mcp__harness_mem__get_project_status` and
`mcp__harness_mem__prepare_session_distill`. Do not select the old
`mcp__harness-mem__...` aliases.

## Mental Model

- `get_project_status`: checks active project and current memory counts.
- `ingest_sessions`: indexes raw local agent session files into harness-mem observations.
- `prepare_session_distill`: one-shot ingest plus recent observation packet for `/hm:distill`.
- `tools/session-distill`: default user-facing distillation playbook that reads evidence and writes pending candidates.
- `auto_review_candidates`: shared low-risk review policy for `/hm:distill` preview. Public MCP forces this tool to preview; `/hm:review` applies explicit confirm/reject decisions.
- `search_memory` / `timeline`: finds prior decisions, errors, discussions, and event history.
- `suggest_*` / `list_candidates` / `confirm_*`: create and review durable memory candidates.
- Cleanup remains an explicit CLI maintenance operation via `harness-mem maintenance purge`, and only soft-deletes harness-mem indexed data.

## Daily Workflow

From the repository root, the user-facing path is IDE command / skill / natural-language agent instruction, not manual CLI. If the client has no slash command surface (for example Cursor through a router), tell the user the natural-language prompt to give the agent instead of listing terminal commands or MCP tool names.

For status and wake-up:

1. Call `get_project_status` to resolve the active project and counts.
2. When the project is ready, call `wake(project_name=<project>)` instead of manually stitching low-level read tools.
3. If the user explicitly wants procedural hints, call `wake(project_name=<project>, include_skill_hints=true)`, and only call `get_skill(skill_id)` if they ask to expand a specific hint.
4. Summarize the usable context and suggest the next IDE-native action:
   - Claude Code: `/hm:distill`, `/hm:review`, or `/hm:wake`.
   - Cursor / Antigravity / opencode / Hermes / generic AI IDE: "用 harness-mem 唤醒当前项目" or "用 harness-mem 整理最近 N 个 session".
   - Do not present terminal commands as the normal answer when MCP tools are available.

If the project has new sessions:

1. Call `prepare_session_distill(project_name=<project>, client="auto", scope="project", project_root=<current project root>)`.
2. Activate repo-local `tools/session-distill`: read the evidence packet, draft candidate claims, apply `grill-before-distill` admission rules, then apply `references/distillation-rules.md`.
3. Write pending candidates only for admitted items. For external claims, evidence may be attached after `suggest_*`, but must be present before confirmation.
4. Call `auto_review_candidates(project_name=<project>, apply=False)`. Show the user a final summary that says auto-review is preview-only and no durable memory was confirmed. If the user wants to apply decisions, route them to `/hm:review` and use explicit `confirm_*` / `reject_*` decisions.

When `grill-before-distill` raises an evidence gap, use the repo-local
`answer-memory-evidence` role. When it raises architecture, product-boundary,
roadmap, or long-lived-rule ambiguity, use `ask-memory-boundary`. Both roles
answer questions only; they do not write or confirm memory.

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

When the user states a durable project rule:

Call MCP `suggest_rule` or `suggest_memory_entry`, then show `list_candidates`; only call `confirm_*` or `reject_*` after the user explicitly decides.

## CLI Fallback

CLI remains the operator interface for install checks, local diagnostics, integration sync, and explicit cleanup previews. Do not present CLI commands as the normal user workflow when MCP tools are available. Only run `harness-mem maintenance purge --apply` after the user approves the exact scope.

## MCP Use

The plugin exposes the MCP server config. MCP is the runtime tool interface used by an agent to call status, ingest, distill, search, timeline, and review tools without asking the user to run every command manually.
