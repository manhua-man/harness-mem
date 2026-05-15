---
name: harness-mem
description: Use harness-mem as a local-first memory runtime for the current project. Trigger when the user asks to remember prior work, resume a project, search old agent sessions, ingest recent Claude/Codex sessions, create durable project rules, or explain what the project currently knows.
---

# harness-mem

## What This Skill Does

Use this skill to operate the local `harness-mem` runtime from a project workspace.

Treat the project as real production context:

- Prefer `doctor`, `status`, `wake`, `search`, and `timeline` before guessing from memory.
- Ingest recent sessions when the project state may be stale.
- Distilled memory is a draft signal. Review it before treating it as durable truth.
- Use `correct` and `confirm` for stable rules the user explicitly wants remembered.
- Do not delete raw Claude/Codex session files unless the user explicitly asks for raw-file cleanup.

## Mental Model

- `doctor`: checks whether memory is initialized and recommends the next action.
- `ingest`: indexes raw local agent session files into harness-mem observations.
- `distill`: extracts draft structured memories from ingested observations.
- `wake`: prints a compact project context block for a new agent session.
- `search`: finds prior decisions, errors, and discussions.
- `correct` / `confirm`: promote a user-approved rule into durable memory.
- `purge`: soft-deletes harness-mem indexed data, not the original raw session files.

## Daily Workflow

From the repository root:

```powershell
python -m harness_mem.cli doctor
python -m harness_mem.cli wake
```

If the project has new sessions:

```powershell
python -m harness_mem.cli ingest claude-code -n 5
python -m harness_mem.cli distill
python -m harness_mem.cli status
```

When looking for prior work:

```powershell
python -m harness_mem.cli search "query words" --mode auto
python -m harness_mem.cli timeline 10
python -m harness_mem.cli show -o <observation-id>
```

When the user states a durable project rule:

```powershell
python -m harness_mem.cli correct
python -m harness_mem.cli candidates
python -m harness_mem.cli confirm <candidate-id>
```

Before cleanup:

```powershell
python -m harness_mem.cli purge -p <project-name> --before <YYYY-MM-DD> --category all --dry-run
```

Only run purge without `--dry-run` after the user approves the exact scope.

## MCP Use

The plugin also exposes the MCP server config. MCP is the runtime tool interface used by an agent to call search/timeline/rules without asking the user to run every command manually.

CLI remains the bootstrap and debug interface. The skill tells the agent when to use the memory runtime. MCP lets the agent use it as a structured tool.

