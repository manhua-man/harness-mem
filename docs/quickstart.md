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

## Register MCP

Most users should connect `harness-mem` through MCP and let their Agent call the
tools.

The server command is:

```bash
python -m harness_mem.mcp.server
```

For Claude Code on Windows, the repo-local installer can add plugin files and
optionally register MCP:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

That install syncs only the Daily `/hm:*` commands by default. To show optional
maintenance or labs commands later, sync command visibility without reinstalling:

```powershell
.\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Maintenance
.\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Labs
```

## Daily Loop

Ask your Agent to use `harness-mem` in plain language:

```text
Use harness-mem to wake this project.
Search harness-mem for the current project convention.
Distill the recent session into memory candidates.
Review the new memory candidates.
```

The stable loop is:

```text
wake -> search -> distill -> review
```

Only confirmed memory is used by `wake` and `search`. `distill` creates
candidates and runs preview-only auto-review by default. New material must pass
`review` before it becomes durable project memory.
