# Quickstart

This is the shortest path to try `harness-mem` in a local Agent workflow.

## Install

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.12 \
  harness-mem==0.9.12
```

The package is distributed through GitHub Releases rather than PyPI. Pip uses
the release asset index above to select the compatible native wheel.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.12 \
  "harness-mem[hybrid]==0.9.12"
```

Check the CLI:

```bash
harness-mem --help
```

Install the seven host-native Daily command surfaces once for this user. The
default command is already `--client all --scope user`:

```bash
harness-mem integration commands sync
```

Every new project can now discover its host-native command. Project identity
and hooks are still adopted separately and automatically on that project's
first MCP initialization.

The CLI is for operator setup, doctor checks, integration sync, and explicit
maintenance. Daily memory work should happen through MCP or `/hm:*` commands.
Maintenance import, soft purge, and privacy erasure are available as
`harness-mem maintenance import`, `harness-mem maintenance purge`, and
`harness-mem maintenance erase`; all preview by default until `--apply` is passed.
Erase apply first writes a content-free durable receipt. If that write fails,
deletion does not start. It then removes eligible native host session files and
the internal reference closure; shared/unsafe native containers remain intact
and return partial failure. Results retain planned, actual, and post-delete
verification counts without copying private content.
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
| Host-native command | Run the Daily workflow through the active IDE's command surface. |
| Plain language | Optional fallback when a host command cannot be used. |
| Agent skills | Teach the client when to call memory tools. |
| Hooks | Inject wake context, stage transcript evidence, and dispatch detached autonomous distillation. |

The server command is:

```bash
harness-mem-mcp
```

This command is installed alongside `harness-mem`, so it always targets the
same Python environment as the package. Verify it in a terminal before adding
it to an IDE. When an IDE does not inherit your terminal `PATH`, configure the
absolute command path from `where harness-mem-mcp` (Windows) or `which
harness-mem-mcp` (macOS/Linux).

For Claude Code on Windows, the repo-local installer can add plugin files and
optionally register MCP:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

That install performs the same all-host user-level command sync by default,
including dream.
For a project-scoped MCP entry, configure its `cwd` as the workspace and set
`HARNESS_MEM_CLIENT` to the host name. The first MCP initialization then adopts
the project and installs the matching hook suite without replacing existing
hooks. OpenCode uses its project plugin; Antigravity uses `.agents/hooks.json`
with `PreInvocation` and `Stop` JSON bridges. The generic hook-suite installer
remains available for operator repair.

Codex requires one native security approval after that automatic install:
open **Settings > Hooks**, review and trust the project's new hooks, then start
a new task. This is not a harness-mem install command. Codex skips untrusted
command hooks, and `get_project_status` reports `hooks=review_required` until
the current `SessionStart` configuration has successfully run.

Autonomous semantic processing requires one separate persistent authorization
because it sends the compact manifest to the configured model provider and may
consume quota:

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
```

Future Stop turns do not ask again. Set the same key to `false` at user or
project scope to retain queue-only Hook behavior.

If Codex connects through MCP Router, internal tool names use the Router alias
(`mcp__mcp_router__*`). A direct `harness_mem` entry uses
`mcp__harness_mem__*`. The generated Daily skills resolve this automatically;
users invoke `$hm-*` and do not type MCP tool prefixes. After changing an MCP
entry or updating the server's tool schema, restart that server and open a new
Codex task because an existing task keeps its original tool snapshot.

## Daily Commands By Host

The one-time user-level sync makes these actions visible in every project. Use
`harness-mem integration commands sync --client <host>` only to refresh one
host independently.

| Host | Command form |
|---|---|
| Claude Code | `/hm:<action>` |
| Codex | `$hm-<action>` |
| Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm-<action>` |

Actions are `status`, `wake`, `search`, `search-all`, `distill`, `review`, and
`dream`. Codex intentionally uses user-invocable skills rather than `/hm:*`:
its slash menu only accepts built-in commands.
The user-level locations are `~/.claude/commands/hm`, `~/.codex/skills`,
`~/.cursor/skills`, `~/.grok/skills`, `$HERMES_HOME/skills`
(`%LOCALAPPDATA%/hermes/skills` on native Windows),
`~/.config/opencode/commands`, and
`~/.gemini/antigravity/global_workflows`, respectively.

Project hooks are normally bootstrapped during first MCP initialization. For
explicit operator repair, use the single all-host command:

```bash
harness-mem integration hooks sync --client all --project-root . --force
```
Replace `all` with one host name when only that integration needs repair.
For the current host support matrix and where each host expects hooks to live,
see [IDE hook adapter matrix](ide-hook-adapter-matrix.md).
Session-start wake shows a compact recent-context index first, including recent
transcript requests, source host, estimated read cost, and drilldown IDs. Stable
truth and active handoffs are appended when available; an un-distilled project
is no longer rendered as three empty sections.
`get_project_status` and CLI status also expose one compact integration line for
the current project, host, hooks, transcript observations, and distill queue.
Compact status keeps the release decisions under its response budget; request
`detail_level="full"` only when you need seven-day outcome/abstention/exclusion
counts, `promoted`/`no_candidate` completion totals, source-cleanup failures,
stuck-reason actions, or the conservative Agent-throughput drain estimate.
Doctor's recovery plan is read-only and risk-classified; preview and apply are
always separate commands.

## Daily Loop

Use the matching host-native command. Plain language remains an optional fallback:

- Continue work: wake/search the current project.
- Remember a reusable result: let distill create evidence-backed candidates.
- Correct memory: review or undo the affected item.

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

Dream is the final stage of the audited maintenance pipeline. A Stop hook
captures an immutable transcript revision and queues every ordered chunk, then
returns immediately while a detached worker consumes an ordered batch of at
most two jobs. The default worker calls the configured Responses endpoint with
no tools, `store=false`, and a strict JSON Schema. Trusted runtime code owns
candidate writes, finalize, and atomic Session Note materialization. The exact
Stop session receives the first worker slot even when the backlog refill budget
is exhausted. Any remaining slot uses three recent jobs followed by one oldest
eligible job, with exponential failure backoff and a daily backlog-refill budget;
older evidence stays parked without deletion.
Each offered job is claimed through
`prepare_session_distill(distill_job_id=...)`, so the worker or an explicit
Agent processes the exact bounded IDs selected by the drainer instead of
reselecting by timestamp.
Automatic worker claims set `run_ingest=false` because the Hook already
synchronized the task; a failed owned job is deferred and does not block later
work. An active review lease is skipped by other workers. Missing provider/auth
setup is reported as retryable rather than background success; `/hm:distill` remains an
explicit immediate/deep-audit entry. In the daily semantic fast path, runtime
hash-verifies and checkpoints each chunk before rendering a coverage-first
indexed exchange manifest.
The configured token value is a soft target for the complete serialized provider
manifest; it may expand with an explicit receipt rather than clip exchanges. The worker then
selects complete semantic windows by exchange index; candidate-grade claims
drill into raw proof only after that selection. Explicit
raw mode retains the full per-chunk lease loop. The provider then performs an
end-of-session review covering the final request, outcome, contradictions,
unfinished work, and evidence status. Only review-ready jobs may create
idempotent `govern_memory(action="suggest")` candidates.
Detected durable-value signals start as `candidate_required`; the provider may
downgrade one only after reading its complete window and recording a
signal-specific session-only explanation. `finalize_session_distill` applies
scoped automatic governance and then Dream only after a fully completed review. An
answered candidate may promote beside an unrelated unfinished handoff without
running Dream. Its
completion block says whether durable knowledge was `promoted` or the session
ended as `no_candidate`; non-promoted candidates are terminally rejected so a
completed low-value session does not return as daily review work. Merely
preparing or partially reading session evidence is never reported as completed.
Health reports actual provider input/output tokens and duration plus the latest
semantic-success, job-completion, and Note-materialization timestamps.
Readable results and Session Notes list each durable memory as a title, one
verifiable fact, and its verification date/status. Internal IDs remain available
only through explicit audit detail.
If an older canonical Storage v2 dataset lacks a derived Observation, the
semantic path rebuilds that projection from the hash-verified immutable
transcript revision. It does not force the Agent back through hundreds of raw
chunks, and a historical repair never replaces a newer canonical projection.

Each new candidate also carries an evidence envelope. Repository claims use a
current project-relative file digest; explicit user preferences/decisions use
a user-authored exchange digest. Transcript-only, missing, changed, or
contradicted evidence is terminally blocked from durable truth. Candidate
detail and full/compact status expose content-free admission outcomes for
audit without adding another MCP tool or manual daily gate.

Successful distill attempts safe source cleanup by default. Only a standalone,
quiet source that passes adapter and CAS/hash checks is deleted; unsupported
shared containers remain untouched. Disable it per project when source evidence
must be retained:

```bash
harness-mem config get distill.delete_source_after_complete
harness-mem config set distill.delete_source_after_complete false --scope project
```

Re-enabling a policy explicitly set to false requires `--confirm`. Finalize
never asks per session. An unreadable config or unresolved project fails safe
to source retention.

When enabled, finalize (and a bounded post-turn retry after an active source
becomes quiet) deletes the eligible native session source plus harness-mem raw
bytes, chunks, checkpoint results, matching Observation/index rows, and linked
evidence-only records. Promoted Memory/Rule/Fact/Skill truth stays readable with
`source_pruned` provenance. The result is always explicit: `retained`,
`deleted`, `partial_failure`, or `unsupported`. A content-free `in_progress`
receipt is durable before native mutation. Shared containers without a safe
per-session transaction remain untouched and report `unsupported`.

## Archived Codex Tasks

Use the explicit operator command to preview or process archived tasks through
the same canonical distill worker:

```bash
harness-mem maintenance archive-distill --dry-run --project-root .
harness-mem maintenance archive-distill --apply --verify --json --project-root .
```

The control project owns the `[archive_distill]` policy: `enabled`,
`batch_size`, `daily_limit`, `order`, `project_scope`, `unresolved_project`,
`allowed_project_roots`, `warn_tokens`, `warn_seconds`,
`require_answer_packet`, and `report_promotions`. Each detected destination
project must separately set `[distill.autonomous].enabled=true`. A completed
row contains a formal Answer Packet and lists each promoted fact with its
destination project and category. Dry-run is read-only and does not consume the
daily ledger.

`--verify` performs one run-bound read-back with the already initialized
backend. It verifies the persisted job and Answer Packet, Note binding, ledger
replay exclusion, promoted truth through its normal store path, and the
source-cleanup receipt. Zero-promotion runs report retrieval as
`not_applicable`; exact-output smoke sessions use a deterministic zero-token
decision while retaining the canonical finalize and cleanup path.

Normal `config list` shows only writable policy. Use
`harness-mem config list --detail runtime` to inspect effective read-only wake,
distill-budget, and Dream timing values with their source labels.

During an Agent run, supported clients should send context/tool/save-point
events to `autopilot_search_tick`. The scheduler calls `search_memory` only
when the event contains a concrete memory-backed uncertainty such as a prior
decision question, convention uncertainty, conflict, tool failure, durable
claim grounding, or long-horizon task switch. Manual `/hm:search` is the
fallback when the client cannot expose those events. `autopilot_search_tick`
never replaces `wake`, and `prepare_session_distill` never pretends to synthesize
truth by itself; it preserves complete resumable raw evidence while offering a
smaller semantic consumption view for the candidate/review loop.
