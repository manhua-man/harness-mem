# harness-mem Plugin

Repo-local integration bundle for `harness-mem`.

Use this plugin when you want an Agent client to talk to the local
`harness-mem` runtime through MCP and user-facing commands.

The plugin is not the canonical API. The canonical boundary is the runtime
package, MCP tool contract, candidate review lifecycle, and local audit state.
Runtime package version and wire format are the source of truth; the repo-local
plugin manifest, skills, and slash command assets mirror that contract.

## What It Includes

- MCP server config for `python -m harness_mem.mcp.server`.
- Claude Code `/hm:*` command files for common memory actions.
- Agent skills that teach the client when to wake, search, distill, and review.
- PowerShell install and doctor helpers.

Invocation paths installed by this plugin:

| Path | Calls |
|---|---|
| `/hm:*` commands | Daily status, wake, search, distill, review, and dream. |
| Agent skills | Memory tool calls selected by the host Agent. |
| Optional MCP registration | User-level `harness_mem` server entry for Claude Code. |

## Install

From the repository root:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

To also register the MCP server with Claude Code:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

Slash command sync installs the Daily command surface:

```text
/hm:status /hm:wake /hm:search /hm:search-all /hm:distill /hm:review /hm:dream
```

`install.ps1` installs or updates the runtime. `sync-commands.ps1` refreshes
the Daily `/hm:*` command files and removes old non-Daily command files; it
does not reinstall the Python package or rerun doctor checks.

`harness-mem doctor` reports plugin drift in two separate buckets:

- repo assets: the checked-in plugin manifest, skill, and Daily slash command
  assets that should match the runtime version and wire format.
- host install: existing Claude Code command and skill files under the user
  profile. Missing host files are not treated as runtime failure; stale existing
  host files are fixed by rerunning `install.ps1` or `sync-commands.ps1`.

The same command visibility sync is available from the CLI:

```powershell
harness-mem integration commands list
harness-mem integration commands sync --profile daily
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
| `/hm:distill <project> <n>` | Immediately consume recent evidence, govern candidates, and run Dream. |
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
- Procedural skill lifecycle governance is outside this plugin and outside the
  public memory MCP surface.
- Agents may suggest memory, but durable truth goes through candidate review.
- Confirmed memory is what future `wake` and `search` consume.

See the repository [README](../../README.md), [Quickstart](../../docs/quickstart.md),
and [Cold-start demo](../../docs/demo-cold-start.md) for the product flow.
