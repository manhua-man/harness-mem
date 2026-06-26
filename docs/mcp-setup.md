# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
python -m harness_mem.mcp.server
```

The server defaults to the `core-read` profile. It exposes read/prepare/review
inspection tools such as `wake`, `search_memory`, `prepare_session_distill`,
`list_candidates`, `get_candidate_detail`, and project status. Deeper read
drilldowns such as `trace_relations`, `search_raw`, `search_skills`, and
`get_skill` require the explicit `review-read` profile.

Candidate suggestion requires the explicit `distill-suggest` profile. Durable
confirm/reject requires `review-write`. Maintenance, labs, and full registry
access are separate opt-in profiles.

For local development you can use:

```bash
HARNESS_MEM_MCP_TOOL_PROFILE=distill-suggest python -m harness_mem.mcp.server
HARNESS_MEM_MCP_TOOL_PROFILE=review-read python -m harness_mem.mcp.server
HARNESS_MEM_MCP_TOOL_PROFILE=review-write python -m harness_mem.mcp.server
```

## Claude Code

On Windows:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

The plugin also includes `/hm:*` command files for common memory actions.
The installer syncs only the Daily command profile by default. Optional command
profiles can be shown later without reinstalling the runtime:

```powershell
.\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Maintenance
.\plugins\harness-mem\scripts\sync-commands.ps1 -Profile Labs
```

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
- CLI import/purge are maintenance-only commands:
  `harness-mem maintenance import` and `harness-mem maintenance purge`; both
  default to dry-run.
- Daily use should happen through the Agent client and MCP tools.
- `distill` creates candidates first and previews review decisions; review
  decides what becomes confirmed memory.
