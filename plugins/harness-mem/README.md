# harness-mem Plugin

Repo-local plugin wrapper for the `harness-mem` local-first AI memory runtime.

It packages three layers:

- Skill: tells an agent when to use memory commands.
- MCP config: exposes `python -m harness_mem.mcp.server` as a structured runtime tool.
- Scripts: install and doctor helpers for local validation.

Install from the repository root:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

Check the current project memory state:

```powershell
.\plugins\harness-mem\scripts\doctor.ps1 -Wake
```

Register the MCP server with Claude Code when desired:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -RegisterClaude
```

This plugin does not delete raw Claude or Codex session files. `ingest` indexes local session data into harness-mem, and `purge` only soft-deletes harness-mem indexed records unless a separate raw-file cleanup is explicitly requested.
