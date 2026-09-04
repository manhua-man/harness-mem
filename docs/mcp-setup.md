# MCP Setup

`harness-mem quickstart` installs the `$hm` or `/hm` entry. It does not inspect
or change MCP connections. Connect `harness-mem-mcp` only when your Agent,
plugin, or MCP Router does not already provide harness-mem.

## Keep one connection

Before adding anything, check the tools available in a new Agent task. If
harness-mem status, wake, or search tools are already available through a
Router or plugin, keep that connection and do not add a direct copy. Two active
copies can expose duplicate tools and may use different working directories.

## Direct connection

The server command is:

```bash
harness-mem-mcp
```

Use the Agent's normal MCP settings to add a project-scoped server:

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

Replace `cursor` with the current Agent: `codex`, `claude-code`, `cursor`,
`grok`, `hermes`, `opencode`, or `antigravity`. Use that Agent's workspace
variable syntax. If it cannot set `cwd`, set `HARNESS_MEM_PROJECT_ROOT` to the
absolute project path instead.

`harness-mem-mcp` is installed with the Python package. If the Agent cannot
find it, use the absolute path reported by `where harness-mem-mcp` on Windows
or `which harness-mem-mcp` on macOS/Linux.

## MCP Router

Register one `harness-mem-mcp` server in the Router, set the current workspace
as its working directory, and grant the active Agent access. Do not also enable
a direct harness-mem entry for the same Agent.

The Router chooses the visible tool prefix. A Router named `mcp_router` may
expose `mcp__mcp_router__get_project_status`; a direct server named
`harness_mem` may expose `mcp__harness_mem__get_project_status`. These are the
same logical tool. Users should use `$hm` or `/hm`, not type these names.

## Restart and verify

After adding or changing the connection:

1. Restart the harness-mem server in the Agent or Router.
2. Start a new Agent task; existing tasks keep the tool snapshot they started with.
3. Ask: `Use harness-mem to check this project.`

Successful verification must identify the current project and current Agent.
If Codex reports that project Hooks need review, open **Settings > Hooks**,
review them, and start another task.

## More detail

- [Quickstart](quickstart.md) covers package and `$hm`/`/hm` installation.
- [Host and Hook support](ide-hook-adapter-matrix.md) lists verified host
  behavior and repair commands.
- [Background memory](background-memory.md) explains the optional automatic
  processing setting.
- [Quickstart privacy and repair](quickstart.md#advanced-and-repair) explains
  local data and deletion behavior.
