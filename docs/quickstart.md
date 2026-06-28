# Quickstart

This is the shortest path to try `harness-mem` in a local Agent workflow.

## Install

```bash
pip install git+https://github.com/manhua-man/harness-mem.git
```

Optional local vector / hybrid search dependencies:

```bash
pip install "harness-mem[hybrid] @ git+https://github.com/manhua-man/harness-mem.git"
```

Check the CLI:

```bash
harness-mem --help
```

The CLI is for operator setup, doctor checks, integration sync, and explicit
maintenance. Daily memory work should happen through MCP or `/hm:*` commands.
Maintenance import and purge operations are available as
`harness-mem maintenance import` and `harness-mem maintenance purge`; both
preview by default until `--apply` is passed.
Other CLI maintenance actions are limited to operator repair and audit tasks
such as index rebuilds, storage migration/export, and state audit.
Procedural skill lifecycle management is outside the public memory MCP and CLI
product surface.

## Register MCP

Most users should connect `harness-mem` through MCP and let their Agent call the
tools.

Common invocation paths:

| Path | Use |
|---|---|
| Plain language | Ask the Agent to wake, search, distill, or review. |
| `/hm:*` commands | Run the daily workflow from Claude Code. |
| Agent skills | Teach the client when to call memory tools. |
| Hooks | Inject wake context at session start or run gated dream maintenance at session end. |

The server command is:

```bash
python -m harness_mem.mcp.server
```

For Claude Code on Windows, the repo-local installer can add plugin files and
optionally register MCP:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

That install syncs the Daily `/hm:*` commands by default, including dream.

## Daily Loop

Ask your Agent to use `harness-mem` in plain language:

```text
Use harness-mem to wake this project.
Search harness-mem for the current project convention.
Distill the recent session into memory candidates.
Review the new memory candidates.
Show the latest dream ledger.
```

The stable loop is:

```text
wake -> search -> distill -> review -> dream ledger
```

Dream is enabled as a default audited maintenance capability. Only confirmed
memory is used by `wake` and `search`; `distill` creates candidates and
preview-only review suggestions. New material must pass `review` before it
becomes durable project memory.
