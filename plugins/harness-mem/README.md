# harness-mem Plugin

Repo-local integration bundle for `harness-mem`.

Use this plugin when you want an Agent client to talk to the local
`harness-mem` runtime through MCP and user-facing commands.

The plugin is not the canonical API. The canonical boundary is the runtime
package, MCP tool contract, candidate review lifecycle, and local audit state.
Runtime package version and wire format are the source of truth; the repo-local
plugin manifest, skills, and slash command assets mirror that contract.

## What It Includes

- MCP server config for the installed `harness-mem-mcp` command.
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

The installer syncs the Daily command surface once at user scope for all seven
supported hosts. New projects discover it without another sync:

```text
/hm:status /hm:wake /hm:search /hm:search-all /hm:distill /hm:review /hm:dream
```

`install.ps1` installs or updates the runtime and runs the all-host user-level
sync. `sync-commands.ps1` refreshes those command files without reinstalling
the Python package or rerunning doctor checks.

`harness-mem doctor` reports plugin drift in two separate buckets:

- repo assets: the checked-in plugin manifest, skill, and Daily slash command
  assets that should match the runtime version and wire format.
- host install: existing Claude Code command and skill files under the user
  profile. Missing host files are not treated as runtime failure; stale existing
  host files are fixed by rerunning `install.ps1` or `sync-commands.ps1`.

The same device-level command visibility sync is available from the CLI. Its
defaults are `--client all --scope user`:

```powershell
harness-mem integration commands list
harness-mem integration commands sync
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

Every supported host exposes the same seven Daily actions through its native
command mechanism. The action names are stable; only the host's prefix differs.

| Host | Invocation |
|---|---|
| Claude Code | `/hm:status`, `/hm:wake`, `/hm:search`, `/hm:distill`, `/hm:review`, `/hm:dream` |
| Codex | `$hm-status`, `$hm-wake`, `$hm-search`, `$hm-distill`, `$hm-review`, `$hm-dream` |
| Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm-status`, `/hm-wake`, `/hm-search`, `/hm-distill`, `/hm-review`, `/hm-dream` |

The repo installer already performs the one-time all-host sync. To repair or
refresh it independently:

```powershell
harness-mem integration commands sync
```

Use `--client codex` to refresh only one host, or `--client codex --scope
project --project-root .` when deliberately creating a repo-local command set.
Hermes is profile-scoped and therefore supports only `--scope user`.
Codex uses skills because its slash menu
only accepts built-in commands; `$hm-*` is its native, user-invocable form.
The generated skills resolve logical MCP tool names against the current task:
Codex behind MCP Router commonly uses `mcp__mcp_router__*`, while a direct
`harness_mem` server uses `mcp__harness_mem__*`. Restart the server and start a
new task after changing registration or upgrading the tool schema.

| Host | User-level discovery directory |
|---|---|
| Claude Code | `~/.claude/commands/hm` |
| Codex | `~/.codex/skills` |
| Cursor | `~/.cursor/skills` |
| Grok | `~/.grok/skills` |
| Hermes | `$HERMES_HOME/skills` (`%LOCALAPPDATA%/hermes/skills` on native Windows) |
| OpenCode | `~/.config/opencode/commands` |
| Antigravity | `~/.gemini/antigravity/global_workflows` |

The underlying actions are:

| Command | Purpose |
|---|---|
| `hm-status` | Check project memory status and next action. |
| `hm-wake` | Recover confirmed project context. |
| `hm-search "query"` | Search current-project memory. |
| `hm-search-all "query"` | Explicit cross-project memory search. |
| `hm-distill <project> <n>` | Immediately consume recent evidence, record promoted/no-candidate completion, and run Dream. |
| `hm-review` | Audit, correct, undo, or replace automatically governed memory. |
| `hm-dream` | Inspect or explicitly trigger the default dream maintenance ledger. |

## Boundary

- MCP is the normal Agent transport.
- CLI is for setup, doctor checks, and explicit maintenance.
- CLI import/purge live under `harness-mem maintenance ...` and preview by
  default.
- Other CLI maintenance actions stay limited to operator repair and audit tasks
  such as index rebuilds, storage migration/export, and state audit.
- Procedural skill lifecycle governance is outside this plugin and outside the
  public memory MCP surface.
- Agents suggest evidence-backed candidates; finalize automatically promotes
  safe truth and terminally rejects the rest. Review is the post-hoc audit and
  correction surface, not a daily manual gate.
- Raw session cleanup defaults off. Enable it persistently with
  `harness-mem config set distill.delete_source_after_complete true --scope user --confirm`;
  the confirmation is required only when enabling this persistent destructive
  policy. An explicit IDE request to enable post-distill source deletion is the
  user's authorization for that confirmed config write;
  every completed job reports retained/deleted/partial_failure/unsupported.
- Confirmed memory is what future `wake` and `search` consume.

See the repository [README](../../README.md), [Quickstart](../../docs/quickstart.md),
and [Cold-start demo](../../docs/demo-cold-start.md) for the product flow.
