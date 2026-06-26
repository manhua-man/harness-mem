# harness-mem Plugin

Repo-local integration bundle for `harness-mem`.

Use this plugin when you want an Agent client to talk to the local
`harness-mem` runtime through MCP and user-facing commands.

The plugin is not the canonical API. The canonical boundary is the runtime
package, MCP tool contract, candidate review lifecycle, and local audit state.

## What It Includes

- MCP server config for `python -m harness_mem.mcp.server`.
- Claude Code `/hm:*` command files for common memory actions.
- Agent skills that teach the client when to wake, search, distill, and review.
- A separate `harness-mem-skill-governance` skill for explicit procedural
  skill inventory review.
- PowerShell install and doctor helpers.

## Install

From the repository root:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

To also register the MCP server with Claude Code:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

Default slash command sync installs only the Daily profile:

```text
/hm:status /hm:wake /hm:search /hm:search-all /hm:distill /hm:review /hm:dream
```

Optional command profiles must be explicit:

```powershell
.\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Maintenance
```

`install.ps1` installs or updates the runtime. `sync-commands.ps1` only changes
which `/hm:*` commands are visible in Claude Code; it does not reinstall the
Python package or rerun doctor checks.

The same command visibility sync is available from the CLI:

```powershell
harness-mem integration commands list
harness-mem integration commands sync --profile daily
harness-mem integration commands enable maintenance
```

Skip slash command and skill sync on headless machines:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -NoSlashCommands
```

Run a local smoke check:

```powershell
.\plugins\harness-mem\scripts\doctor.ps1 -Wake
```

## Daily Commands

Use these from Claude Code after installation:

| Command | Purpose |
|---|---|
| `/hm:status` | Check project memory status and next action. |
| `/hm:wake` | Recover confirmed project context. |
| `/hm:search "query"` | Search current-project memory. |
| `/hm:search-all "query"` | Explicit cross-project memory search. |
| `/hm:distill <project> <n>` | Convert recent session evidence into reviewable candidates and preview review decisions. |
| `/hm:review` | Confirm, reject, replace, or keep pending candidates. |
| `/hm:dream` | Inspect or explicitly trigger the default dream maintenance ledger. |

For Cursor, Gemini CLI, Codex, Hermes, or another MCP-capable client, use the
same actions in natural language:

```text
Use harness-mem to wake this project.
Search harness-mem for "release boundary".
Use harness-mem to distill the recent session into memory candidates.
Review the new harness-mem candidates.
```

## Boundary

- MCP is the normal Agent transport.
- CLI is for setup, doctor checks, and explicit maintenance.
- CLI import/purge live under `harness-mem maintenance ...` and preview by
  default.
- Other CLI maintenance actions stay limited to operator repair and audit tasks
  such as index rebuilds, storage migration/export, and state audit.
- Procedural skill lifecycle governance uses the explicit
  `harness-mem skill-governance ...` CLI workflow and the
  `harness-mem-skill-governance` skill; it is not a public MCP lifecycle tool
  and not a Daily `/hm:*` command.
- Agents may suggest memory, but durable truth goes through candidate review.
- Confirmed memory is what future `wake` and `search` consume.

See the repository [README](../../README.md), [Quickstart](../../docs/quickstart.md),
and [Cold-start demo](../../docs/demo-cold-start.md) for the product flow.
