# harness-mem plugin assets

This directory contains the host-facing assets shipped beside the
`harness-mem` runtime. The Python runtime and MCP tool contract remain the
implementation authority; these files only tell an Agent how to use them.

## What is included

- one canonical memory entry at `commands/hm/hm.md`;
- the Codex plugin manifest and MCP declaration;
- PowerShell helpers for editable development installs and entry refreshes.

The public daily surface is exactly one entry:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Use ordinary language after invoking it:

```text
记住这次
找一下以前怎么做的
这条记忆不对
```

## Development install

From the repository root:

```powershell
.\code\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

The script installs the editable Python package only. It does not modify MCP
settings or install entries for every Agent app. Run Quickstart once for each
Agent app you actually use, not once per project:

```powershell
harness-mem quickstart
```

If app detection is unavailable, specify it once, for example:

```powershell
harness-mem quickstart --client codex
```

Quickstart reports only that the entry was installed. Start a new Agent task so
the app discovers it. The same entry then works in every project; its first use
prepares local memory and Hooks for that project.

Refresh the entry explicitly without reinstalling the package:

```powershell
harness-mem integration commands sync --client codex
```

The refresh removes old harness-mem action entries at their exact product paths
and preserves unrelated user files. To refresh all supported apps deliberately:

```powershell
.\code\plugins\harness-mem\scripts\sync-commands.ps1 -Client all
```

Repair only the current project's Hook files with:

```powershell
harness-mem integration hooks sync --client codex --project-root . --force
```

Neither Quickstart nor these command-entry helpers inspect or change MCP
connections. The Agent, Router, plugin, or other tool that owns those settings
must expose `harness-mem-mcp` separately. If one of them already exposes it, do
not add a duplicate connection.

## Boundaries

- MCP is the normal Agent transport.
- The CLI is for setup, diagnosis, integration repair, and explicit maintenance.
- Project Hooks capture lifecycle events and wake the same local runtime; they
  do not create a second memory implementation.
- Agents propose evidence-backed changes; local verification and finalize own
  durable writes.
- Raw session sources are retained unless an operator separately authorizes
  cleanup and the source passes the required safety checks.

See the public [README](https://github.com/manhua-man/harness-mem),
[Quickstart](https://github.com/manhua-man/harness-mem/blob/main/docs/quickstart.md),
and [MCP setup](https://github.com/manhua-man/harness-mem/blob/main/docs/mcp-setup.md).
