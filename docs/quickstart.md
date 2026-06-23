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

Only confirmed memory is used by `wake` and `search`. New material starts as a
candidate and must be reviewed before it becomes durable project memory.
