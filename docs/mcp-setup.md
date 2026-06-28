# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

## Server Command

Use this command in your MCP client configuration:

```bash
python -m harness_mem.mcp.server
```

The server has one public memory surface. It exposes the normal Agent workflow:
status, wake/search, session ingest/distill, candidate suggestion, explicit
candidate review, and dream as the default audited maintenance capability.
Historical profile values are ignored.

Invocation paths are Agent MCP calls, `/hm:*` commands, installed skills, and
explicit IDE hooks. Session-start hooks inject wake context; session-end hooks
run gated dream maintenance.

`auto_review_candidates` is always preview-only on the public MCP surface.
Durable memory changes go through explicit `confirm_*`, `reject_*`, or
supersede tools. Operator maintenance and skill lifecycle management are not
public MCP tools.
Read-only procedural hints can be searched from memory context, but procedural
skill lifecycle management is outside this public memory surface.

## Operator Maintenance Profile

Metabolism and reflection jobs are internal background governance mechanisms,
similar to an indexer, compaction worker, repair worker, or GC. Product-facing
flows should describe the outcome instead: memory is automatically organized,
deduplicated, expired, repaired, and consolidated.

The public MCP surface does not list these internals, does not report hidden
maintenance counts, and treats direct calls to maintenance-only tools as
unknown. Operators can start a controlled read/debug profile when diagnosing
local state:

```bash
HARNESS_MEM_MCP_MAINTENANCE=1 python -m harness_mem.mcp.server
```

Then request `profile=maintenance` from the MCP client. This profile is
read-only and only lists:

- `list_reflection_jobs`
- `get_reflection_job`
- `list_metabolism_runs`
- `health_summary`
- `surface_cost_report`

It does not expose `metabolism_preview` or `metabolism_run`; the maintenance
profile cannot trigger metabolism or write suggestion candidates.

## Claude Code

On Windows:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

The plugin also includes the Daily `/hm:*` command files for common memory
actions, including dream.

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
- Skill lifecycle governance is outside the public memory MCP and CLI product
  surface.
- Daily use should happen through the Agent client and MCP tools.
- `distill` creates candidates first and previews review decisions; review
  decides what becomes confirmed memory.
