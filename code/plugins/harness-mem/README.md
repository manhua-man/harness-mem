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
- One daily command: `$hm` in Codex and `/hm` in the other supported hosts.
- Agent instructions that turn ordinary requests into the existing memory tools.
- Optional `grill-with-docs` for explicit, user-led design clarification and
  confirmed glossary/ADR maintenance; it is not part of unattended distill.
- PowerShell install and doctor helpers.

Invocation paths installed by this plugin:

| Path | Calls |
|---|---|
| `$hm` / `/hm` | Remember this session, find earlier work, or correct a memory. |
| Legacy action commands | Compatibility and advanced diagnosis only. |
| Agent skills | Memory tool calls selected by the host Agent. |
| Optional MCP registration | User-level `harness_mem` server entry for Claude Code. |

## Install

From the repository root:

```powershell
.\code\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

To also register the MCP server with Claude Code:

```powershell
.\code\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

The installer syncs the daily command once at user scope for all seven
supported hosts. New projects discover it without another sync:

```text
Codex: $hm
Other hosts: /hm
```

The older `hm-status`, `hm-wake`, `hm-search`, `hm-search-all`, `hm-distill`,
`hm-review`, and `hm-dream` entries remain installed for compatibility and
advanced diagnosis. Ordinary users do not need to learn them.

`install.ps1` installs or updates the runtime and runs the all-host user-level
sync. `sync-commands.ps1` refreshes those command files without reinstalling
the Python package or rerunning doctor checks.

`harness-mem doctor` reports plugin drift in two separate buckets:

- repo assets: the checked-in plugin manifest, daily command, and compatibility
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

Repair one host's project hook suite without reinstalling the package:

```powershell
harness-mem integration hooks sync --client codex --project-root . --force
```

Skip slash command and skill sync on headless machines:

```powershell
.\code\plugins\harness-mem\scripts\install.ps1 -NoSlashCommands
```

Run a local smoke check:

```powershell
.\plugins\harness-mem\scripts\doctor.ps1 -Wake
```

## Everyday Use

Every supported host exposes one daily entry through its native command
mechanism.

| Host | Invocation |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Use normal language after invoking it:

```text
记住这次
找一下以前怎么做的
这条记忆不对
```

Wake runs automatically when a session starts. Authorized Dream work runs in
the background. Cross-project search happens only when the user explicitly
asks for it.

The repo installer already performs the one-time all-host sync. To repair or
refresh it independently:

```powershell
harness-mem integration commands sync
```

Use `--client codex` to refresh only one host, or `--client codex --scope
project --project-root .` when deliberately creating a repo-local command set.
Hermes is profile-scoped and therefore supports only `--scope user`.
Codex uses a skill because its slash menu only accepts built-in commands;
`$hm` is its native, user-invocable form.
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

The older action-specific entries remain available for compatibility and
advanced diagnosis:

| Command | Purpose |
|---|---|
| `hm-status` | Check project memory status and next action. |
| `hm-wake` | Recover confirmed project context. |
| `hm-search "query"` | Search current-project memory. |
| `hm-search-all "query"` | Explicit cross-project memory search. |
| `hm-distill <project> <n>` | Process recent evidence in the active host, challenge zero-candidate conclusions, and finalize only that explicit session job. |
| `hm-review` | Audit, correct, undo, or replace automatically governed memory. |
| `hm-dream` | Inspect or explicitly trigger authorized project-level knowledge governance. |

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
- Raw session sources are retained by default. Cleanup is allowed only after an
  operator explicitly sets `distill.delete_source_after_complete=true` with
  `--confirm`; supported standalone sources must still pass quiet/CAS/hash
  checks, and every completed job reports the actual cleanup result.
- Confirmed memory is what future `wake` and `search` consume.

See the public [README](https://github.com/manhua-man/harness-mem),
[Quickstart](https://github.com/manhua-man/harness-mem/blob/main/docs/quickstart.md),
and [Cold-start demo](https://github.com/manhua-man/harness-mem/blob/main/docs/demo-cold-start.md)
for the product flow.
