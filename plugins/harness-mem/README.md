# harness-mem Plugin

Repo-local plugin wrapper for the `harness-mem` local-first AI memory runtime.

It packages four layers:

- **Skill**: tells an agent when to use memory commands.
- **MCP config**: exposes `python -m harness_mem.mcp.server` as `harness_mem` structured runtime tools.
- **Slash commands**: `/hm:status`, `/hm:distill`, `/hm:wake`, `/hm:search`, plus optional `/hm:review` —
  ready-to-use Claude Code slash commands so end users never need to memorize CLI flags.
- **Scripts**: install and doctor helpers for local validation.

Install from the repository root:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

This:

1. Installs `harness-mem` (with `[hybrid]` extras when requested).
2. Copies the slash commands from `plugins/harness-mem/commands/hm/` into
   `~/.claude/commands/hm/` so they show up in any Claude Code project.
3. Runs `harness-mem doctor` for a smoke check.

Skip slash command sync (e.g. for headless/CI machines):

```powershell
.\plugins\harness-mem\scripts\install.ps1 -NoSlashCommands
```

Check the current project memory state:

```powershell
.\plugins\harness-mem\scripts\doctor.ps1 -Wake
```

Register the MCP server with Claude Code when desired:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -RegisterClaude
```

Claude Code tool names should use the no-hyphen alias, for example
`mcp__harness_mem__get_project_status`. Avoid registering the server as
`harness-mem`; some Claude Code tool-call paths misparse MCP server names that
contain `-`.

## Daily flow inside Claude Code

Once installed, drive harness-mem entirely through slash commands and chat:

| Slash | What it does |
|-------|--------------|
| `/hm:status` | Project health check (delegates to `harness-mem doctor`). |
| `/hm:distill <project> <n>` | Call MCP `prepare_session_distill` once, run `tools/session-distill`, auto-judge and handle low-risk candidates, then show a final review summary. This is the normal closed-loop path. |
| `/hm:review` | Optional repair/recheck command for pending candidates left over from old runs, high-risk suggestions, or user corrections. Not part of the daily happy path. |
| `/hm:wake` | Pull project profile, recent task handoffs, confirmed rules, and recent observations as fresh-session context. |
| `/hm:search "query"` | Hybrid memory search via MCP `search_memory`. |

This plugin does not delete raw Claude or Codex session files. `ingest` indexes
local session data into harness-mem, and `purge` only soft-deletes harness-mem
indexed records unless a separate raw-file cleanup is explicitly requested.
