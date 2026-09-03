# MCP Setup

`harness-mem` is designed to be used by MCP-capable Agent clients.

This connection is managed by the Agent, MCP Router, plugin, or another setup
tool. `harness-mem quickstart` does not inspect or change MCP settings.

## Server Command

Use this command in your MCP client configuration:

```bash
harness-mem-mcp
```

For a project-scoped MCP entry, set the server's working directory to the
workspace and pass the owning client in `HARNESS_MEM_CLIENT`. On its first
`initialize` request, a recognized client automatically records the project
profile, makes it active, and installs its hook suite without overwriting
existing hook files. It does not install or refresh user-level commands;
Quickstart owns that separate one-time setup.

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

`harness-mem-mcp` is installed alongside `harness-mem` and therefore starts
the server from the same Python environment as the installed package. Verify
the command in a terminal before adding it to the IDE. If the IDE does not
inherit that terminal `PATH`, use the absolute path reported by `where
harness-mem-mcp` (Windows) or `which harness-mem-mcp` (macOS/Linux) as the
`command` value.

Use the client-specific syntax for the workspace variable: `cursor`,
`claude-code`, `grok`, `codex`, `hermes`, `opencode`, and `antigravity` are recognized. Where
a client cannot set `cwd`, set `HARNESS_MEM_PROJECT_ROOT` to the absolute
workspace path instead. The environment value belongs in the MCP server entry,
not only the hook command, so initialization sees the correct host identity.

The callable tool prefix is chosen by the MCP client configuration, not by
harness-mem. A direct server named `harness_mem` commonly exposes
`mcp__harness_mem__*`; Codex connected through a server named `mcp_router`
exposes the same logical tools as `mcp__mcp_router__*`. The daily command and
host instructions resolve `wake`, `get_project_status`, `prepare_session_distill`, and the
other logical names from the current task's tool inventory. Users do not type
these internal prefixes.

Do not keep both a direct harness-mem entry and a Router-imported copy enabled
for the same host. Pick one transport. When the server implementation or tool
schema changes, restart the harness-mem child process in the Router and start a
new Agent task; existing tasks keep the tool snapshot they started with.

`harness_mem/mcp/tool_specs.py` and `code/mcps/harness_mem/tools/` are the canonical
descriptor sources. The stale checked-in Router aggregate snapshots were
removed in 0.9.6. This does not remove the live `mcp__mcp_router__*` namespace:
Router clients continue to discover tools from the running server.

The server has one public memory surface. It exposes status, wake/search,
session distill, composite `govern_memory`, candidate review, and Dream as the
audited maintenance capability. Historical profile values are ignored.

Unattended Dream processing is disabled until a project makes an explicit
project-scoped choice. Ordinary setup does not require the internal audit
fields; see [`docs/background-memory.md`](background-memory.md) only when
diagnosing background work.

1. **`distill.autonomous.enabled=true`** — consent for this repository to run
   background host CLI work for the current client.

Turn off background work with **`distill.autonomous.enabled=false`** only. See
[`docs/background-memory.md`](background-memory.md).

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
```

Without background authorization (`enabled=true`), Hook-captured jobs remain
safely queued. An explicit `distill` stays in the active host.

Authorized background work defaults to the **current host CLI** for the Hook's
`host_client` / `HARNESS_MEM_CLIENT`. A project can set `distill.autonomous.cli`
to Codex, Hermes, Claude Code, or OpenCode instead. Transport and credentials
belong in the selected CLI config—not harness-mem project config. The checks
verify `execution_mode=agent` and `provider.name=<host>_cli`.

The `wake` output leads with a recent project-scoped context index. It is a
derived view of transcript observations and does not promote them to confirmed
truth; stable truth and active handoffs remain separate sections.
`get_project_status` includes `integration_health.summary` for a concise check
of project root, configured host, installed hooks, transcript observations, and
pending distill work. Missing `HARNESS_MEM_CLIENT` is reported as `unknown`.
For Codex, `hooks=review_required` means the project manifest was installed but
the current Hook configuration has not yet executed. Open **Codex Settings >
Hooks**, trust the project hooks, and start a new task. The status changes to
`ok` only after the matching `SessionStart` Hook completes; changing the Hook
manifest invalidates the old execution receipt.

Invocation paths are the host-native daily command, installed Agent
instructions, MCP calls, and explicit IDE hooks. Session-start/PreInvocation
hooks inject read-only wake context; runtime task hooks call
`autopilot_search_tick`, which
decides whether to run bounded `search_memory`. A save-point or session-end
Hook saves evidence, creates or advances its exact session job, and emits a
source-bound Dream activity signal. It does not read knowledge, call a provider,
or write long-term knowledge.

`wake` stays read-only. It never claims `distill_maintenance`, selects a queue
job, or asks the current Agent to perform background semantic work. When users
ask `$hm` or `/hm` to remember the current session immediately, that work stays
in the current host; unattended Hook-started work is processed only by
authorized Dream. `get_project_status` reports state without executing either
path.

`autopilot_search_tick` is the event-level scheduler. PI
`transformContext` / `tool_result` / `prepareNextTurn`, Claude Code
`PostToolUse`, and Cursor after-agent hooks should map their native event
payloads into that tool. It searches only for concrete uncertainty, conflict,
tool failure, durable-claim grounding, or long-horizon task switches; it is not
a second `wake`.

`prepare_session_distill` optionally claims one active `distill_job_id`,
syncs native transcript revisions, and preserves every
ordered raw chunk. Daily `evidence_mode="semantic", detail_level="compact"`
lets runtime hash-verify and checkpoint each chunk before returning a
deterministic indexed manifest. `budget_tokens` is an advisory target for the
complete serialized response. The runtime measures the exact Agent-visible JSON
and reports any coverage/full/drilldown expansion; it never clips the final JSON
or drops later exchanges. The Agent selects complete semantic
windows with `drilldown_exchange_indexes`, then reads raw chunk proof only when
a candidate needs it. Explicit `detail_level="full"` or `evidence_mode="raw"`
keeps the original resumable lease loop: chunks are never shortened to fit one
MCP response, and long sessions continue over multiple calls. For older
datasets, a missing derived Observation is reconstructed on demand
from the byte-verified immutable transcript revision. Historical projections
remain in-memory so they cannot replace a newer canonical search projection.
After structural coverage and semantic reading complete, the Agent submits a structured
end-of-session review. Candidate writes
bound to that job use stable IDs so retries do not duplicate memory.
`finalize_session_distill` applies the shared automatic policy and completes
that one explicit active-host job. It does not start a second unattended Dream
run; Hook-started Dream is the separate background path. It returns `completion`, `promotion`,
`queue_effect`, and `source_cleanup` summaries. Safe candidates enter the
truth layer; everything else is terminally rejected instead of becoming a
recurring daily prompt. When a user says a memory is wrong through `$hm` or
`/hm`, the Agent uses the existing correction and undo path. Lower-level sync
and chunk tools are internal Agent workflow, not user commands. Operator
maintenance and skill lifecycle management are not public MCP tools.

New candidates use `govern_memory(action="suggest")` with
`evidence_basis`, `verification_outcome`, and integrity-only
`verification_refs` inside its existing `arguments` object. Repository claims
use a project-relative locator plus current file SHA-256; explicit user
preferences/decisions use a user-role exchange index plus semantic-window
SHA-256. The runtime rechecks reference integrity before admission.
Transcript-only, outside-project, missing, changed, or contradicted evidence
cannot enter readable truth. It derives an `answer_gate` status from that
recheck; only `ANSWERED` is promotion-eligible, while `PARTIAL`,
`UNANSWERED`, `CONTRADICTED`, `STALE`, and `NOT_APPLICABLE` are blocked.
Relation facts use the same scoped policy and the
public MCP allowlist remains exactly 27 tools.

`distill.delete_source_after_complete` is a project-scoped config boolean and
defaults to `false`. A completed job attempts the cleanup saga only after the
project explicitly opts in:
receipt first, native compare-and-swap deletion,
local raw/chunk/Observation/index cleanup, truth provenance sanitization, and
post-delete verification. `source_cleanup.status` distinguishes `retained`,
`deleted`, `partial_failure`, and `unsupported`; a configured policy never
implies that deletion succeeded. Shared SQLite/JSONL sources are not unlinked
when a safe session-scoped transaction is unavailable.

Enable it only when the project permits original session source deletion:

```powershell
harness-mem config set distill.delete_source_after_complete true --scope project --confirm
```

User-level values do not authorize cleanup. Invalid config, a missing project
opt-in, or unresolved project context fails safe to retention.
Read-only procedural hints can be searched from memory context, but procedural
skill lifecycle management is outside this public memory surface.

## Operator Maintenance

Archived Codex tasks use
`harness-mem maintenance archive-distill --dry-run|--apply`. The command detects
the destination project from each rollout `cwd`, enforces the control project's
`[archive_distill]` batch/daily/project/cost/report policy, requires autonomous
authorization in each destination project, and emits a formal Answer Packet
plus per-fact promotion details. `config list --detail runtime` exposes the
effective read-only wake, distill-budget, and Dream timing values.

Metabolism and reflection jobs are internal background governance mechanisms,
similar to an indexer, compaction worker, repair worker, or GC. Product-facing
flows should describe the outcome instead: memory is automatically organized,
deduplicated, expired, repaired, and consolidated.

MCP has no maintenance profile. The public MCP surface does not list these
internals, does not report hidden maintenance counts, and treats direct calls
to maintenance-only tools as unknown. Operators should diagnose local state
through `harness-mem doctor` and explicit CLI maintenance commands.

Storage migration uses an automatic pre-migration SQLite snapshot, a staging DB,
integrity/checksum-relation validation, atomic activation, and runtime-state-last
switching. Doctor distinguishes `exact_match`, `canonical_superset_expected`,
`legacy_missing_in_canonical`, `content_conflict`, and `invalid_legacy`.
Doctor probes the database through a read-only connection and classifies each
possible recovery as `safe_rebuild`, `snapshot_required`, `manual_review`, or
`destructive`. The report may name exact preview and apply commands, but
`automatic_apply_allowed` remains false; corruption fails closed.
`maintenance migrate-legacy-accepted` is dry-run by default and can only move old
`accepted` rows to pending review or historical/superseded state; it never confirms truth.
`maintenance rebuild-vector-index --batch-size 32` preserves old vectors until
batched staging rows validate, then switches transactionally and rebuilds vec0 once.
`maintenance erase` also previews by default. Apply persists an `in_progress`
content-free receipt before deleting anything, then records `succeeded`,
`skipped`, or `partial_failure` with planned/actual counts and post-delete
verification. Receipt persistence failure prevents the destructive phase.

Full project status includes a project-isolated seven-day quality scorecard for
surfaced, used, ignored, misleading, abstained, historical/stale excluded,
conflict excluded, and insufficient-feedback counts. Missing outcome feedback
is not treated as poor feedback. Backlog diagnostics distinguish daily-budget
exhaustion, retry backoff, waiting for the active lane, and zero Agent
throughput; drain estimates explicitly require Agent execution and never imply
background semantic processing.

## Claude Code

On Windows:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\code\plugins\harness-mem\scripts\install.ps1 -WithHybrid
harness-mem quickstart --client claude-code
```

Quickstart installs the one global entry for the selected host. Codex uses
`$hm`; Claude Code, Cursor, Grok, Hermes, OpenCode, and Antigravity use `/hm`.
The editable install script does not change MCP settings or install entries for
other apps. On the first `hm` use in a project, the status call prepares the
project and its Hooks. A workspace-scoped MCP initialization may prepare them
earlier. Existing unrelated Hook files are not overwritten.

For explicit hook repair across any supported host, use
`harness-mem integration hooks sync --client <host> --project-root . --force`.
The old host-specific hook installer commands are not public CLI surfaces.

## Generic MCP Client

Add a project-scoped server entry that runs from the workspace:

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

Replace `cursor` with the actual MCP host. For an unrecognized generic client,
omit the client variable; regular MCP tools still work, while automatic hook
installation is skipped.

### MCP Router

Register one `harness-mem` server in the Router using `harness-mem-mcp` (or its
absolute installed path), set the workspace as its context/cwd, and grant the
active Agent client access. The Router server name becomes the Agent-visible
namespace. For example, a Codex entry named `mcp_router` exposes
`mcp__mcp_router__get_project_status`, not
`mcp__harness_mem__get_project_status`.

Router project groups such as `Unassigned` are organizational metadata; verify
client access in the Router's app-integration settings rather than inferring it
from the group label. A stopped duplicate usually comes from importing an
external IDE MCP config. Disable the duplicate and keep the single entry whose
command, context path, and installed Python environment are correct.

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
- Daily use should happen through `$hm` in Codex or `/hm` in the other hosts;
  the Agent uses the existing MCP tools underneath.
- `distill` creates candidates only after complete evidence review;
  `finalize_session_distill` applies the shared automatic governance policy to
  that explicit active-host job only. Hook-started Dream is the separate
  unattended path. A user correction through `$hm` or `/hm` uses the post-hoc
  audit and undo path; it is not a required promotion gate.
