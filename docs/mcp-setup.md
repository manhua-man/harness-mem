# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
python -m harness_mem.mcp.server
```

The server exposes memory tools such as `wake`, `search_memory`,
`prepare_session_distill`, candidate review, and project status.

## Claude Code

On Windows:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

The plugin also includes `/hm:*` command files for common memory actions.

## Generic MCP Client

Add a server entry that runs:

```json
{
  "command": "python",
  "args": ["-m", "harness_mem.mcp.server"]
}
```

After registration, ask the Agent to:

```text
Use harness-mem to wake this project.
Search harness-mem for the relevant project decision.
```

## Notes

- The CLI is mainly for setup, doctor checks, and maintenance.
- Daily use should happen through the Agent client and MCP tools.
- `distill` creates candidates first; review decides what becomes confirmed
  memory.
