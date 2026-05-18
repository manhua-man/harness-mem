---
name: harness-mem
description: Use harness-mem as a local-first memory runtime for the current project. Trigger when the user asks to remember prior work, resume a project, search old agent sessions, ingest recent Claude/Codex sessions, create durable project rules, or explain what the project currently knows.
---

# harness-mem

## What This Skill Does

Use this skill to operate the local `harness-mem` runtime from a project workspace.

Treat the project as real production context:

- Prefer MCP tools (`get_project_status`, `wake`-style reads, `search_memory`, `timeline`) before guessing from memory.
- Ingest recent sessions through MCP `ingest_sessions` when the project state may be stale.
- Use repo-local `tools/session-distill` for user-triggered distillation; `distill_sessions` is only a smoke/fallback extractor.
- Distilled memory is a draft signal. Review it before treating it as durable truth.
- Use `suggest_*`, `list_candidates`, and `confirm_*` / `reject_*` for stable rules the user explicitly wants remembered.
- Do not delete raw Claude/Codex session files unless the user explicitly asks for raw-file cleanup.

In Claude Code, prefer the no-hyphen MCP alias names such as
`mcp__harness_mem__get_project_status` and
`mcp__harness_mem__prepare_session_distill`. Do not select the old
`mcp__harness-mem__...` aliases.

## Mental Model

- `get_project_status`: checks active project and current memory counts.
- `ingest_sessions`: indexes raw local agent session files into harness-mem observations.
- `prepare_session_distill`: one-shot ingest plus recent observation packet for `/hm:distill`.
- `tools/session-distill`: default user-facing distillation playbook that reads evidence and writes pending candidates.
- `distill_sessions`: low-cost heuristic fallback that extracts obvious draft structured memories.
- `search_memory` / `timeline`: finds prior decisions, errors, discussions, and event history.
- `suggest_*` / `list_candidates` / `confirm_*`: create and review durable memory candidates.
- `purge` remains a CLI/debug operation for explicit cleanup, and only soft-deletes harness-mem indexed data.

## Daily Workflow

From the repository root, the user-facing path is slash/MCP, not manual CLI.

For status and wake-up:

1. Call `get_project_status` to resolve the active project and counts.
2. Call `get_project_profile`, `get_task_handoffs`, `get_confirmed_rules`, and `timeline`.
3. Summarize the usable context and suggest `/hm:distill`, `/hm:review`, or `/hm:wake`.

If the project has new sessions:

1. Call `prepare_session_distill(project_name=<project>, client="auto", scope="project", project_root=<current project root>)`.
2. Activate repo-local `tools/session-distill`: read the returned evidence packet, apply `references/distillation-rules.md`, and write pending candidates with `suggest_memory_entry`, `suggest_rule`, `suggest_relation_fact`, or `create_task_handoff`.
3. Call `list_candidates(project_name=<project>, status="pending")` and ask the user what to confirm or reject.

Call `distill_sessions(project_name=<project>, project_root=<current project root>)` only when the user explicitly asks for a quick fallback, when testing MCP availability, or when debugging the runtime.

When looking for prior work:

Call MCP `search_memory(project_name=<project>, query=<query>, mode="auto")`, then use `timeline` or `get_observations` for provenance.

When the user states a durable project rule:

Call MCP `suggest_rule` or `suggest_memory_entry`, then show `list_candidates`; only call `confirm_*` or `reject_*` after the user explicitly decides.

## CLI Fallback

CLI remains the bootstrap/debug interface for install checks, local diagnostics, and explicit cleanup previews. Do not present CLI commands as the normal user workflow when MCP tools are available. Only run purge without `--dry-run` after the user approves the exact scope.

## MCP Use

The plugin exposes the MCP server config. MCP is the runtime tool interface used by an agent to call status, ingest, distill, search, timeline, and review tools without asking the user to run every command manually.
