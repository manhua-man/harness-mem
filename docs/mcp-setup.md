# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
python -m harness_mem.mcp.server
```

The server has one public memory surface. It exposes the normal Agent workflow:
status, wake/search, session ingest/distill, candidate suggestion, explicit
candidate review, and dream maintenance. Historical `mcp_tool_profile` or
`HARNESS_MEM_MCP_TOOL_PROFILE` values are ignored so clients do not need to
choose between `full`, `minimal`, `labs`, or review profiles.

`auto_review_candidates` is always preview-only on the public MCP surface.
Durable memory changes go through explicit `confirm_*`, `reject_*`, or
supersede tools. Operator maintenance and skill lifecycle management are not
public MCP tools.
Read-only procedural hints can be searched from memory context, but promotion,
rejection, and outcome tracking for procedural skills use the separate
`harness-mem skill-governance ...` operator workflow.

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
- Other CLI maintenance actions stay limited to operator repair and audit tasks
  such as index rebuilds, storage migration/export, and state audit.
- Skill lifecycle governance is outside MCP; use
  `harness-mem skill-governance ...` only for explicit procedural skill review.
- Daily use should happen through the Agent client and MCP tools.
- `distill` creates candidates first and previews review decisions; review
  decides what becomes confirmed memory.
