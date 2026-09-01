# Quickstart

This is the shortest path to try `harness-mem` in a local Agent workflow.

## Install

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  harness-mem==0.9.26
```

The package is distributed through GitHub Releases rather than PyPI. Pip uses
the release asset index above to select the compatible native wheel.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  "harness-mem[hybrid]==0.9.26"
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
| Hooks | Inject wake context, stage transcript evidence, create/advance its job, and wake Dream with the immutable session revision. |

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
.\code\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
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

Unattended Dream processing needs **`distill.autonomous.enabled=true`**.
Background work defaults to the current host CLI. A project can instead set
`distill.autonomous.cli` to `codex`, `claude-code`, `hermes`, or `opencode`. See
[`docs/background-memory.md`](background-memory.md).

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
```

Authorized background work uses the selected CLI (`codex_cli`, `hermes_cli`,
`claude-code_cli`, or `opencode_cli`). An unsupported current host is reported;
it is not replaced with Codex. The checks require honest `execution_mode=agent` receipts with
`provider.name=<host>_cli`. Local worker manifest, Answer Gate, assimilation,
and finalize are unchanged. An explicit `distill` still runs in the active host.

Future Stop turns do not ask again. Set **`distill.autonomous.enabled=false`**
to retain queue-only Hook behavior.

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

## Daily actions and core feedback

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

These commands are user actions, not a mandatory linear sequence. The
architecture is `session intake and lifecycle -> extraction -> verification ->
assimilation -> retrieval/use`; see [memory-adoption.md](memory-adoption.md).

```text
explicit distill -> active host: extract -> verify -> assimilate

Stop Hook -> immutable revision + job + Dream activity signal
          -> authorized Dream: session + project governance
          -> extract or compare -> verify -> assimilate

review -> optional post-hoc audit / correction / undo
```

Dream is a governance-feedback capability across assimilation and retrieval; it
can identify stale, duplicate, conflicting, mergeable, or replaceable knowledge
and return it to source-backed verification and assimilation. A Hook never
executes that work. Its source-bound signal is either processed by an authorized
Dream run or remains safely queued. Disabled authorization or an unavailable
host CLI produces a retryable setup result, never a background success.

Both execution paths preserve all ordered chunks, checkpoint work for resume,
and fail closed when evidence is incomplete or contradicted. Only **local
harness-mem (Dream/worker/finalize)** writes candidates, records a Session
Note, and mutates SQLite current knowledge. The **model step** runs through the
authorized host CLI agent (no Hook re-entry, strict schema); the token budget
is a soft response target and never permits silent loss of an evidence window. `finalize_session_distill` commits only the
explicit active-host job; it does not start a separate Dream run. Merely
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

Successful distill retains source evidence by default. Only a project-level
explicit opt-in can authorize cleanup, and only a standalone, quiet source that
passes adapter and CAS/hash checks is deleted; unsupported shared containers
remain untouched:

```bash
harness-mem config get distill.delete_source_after_complete
harness-mem config set distill.delete_source_after_complete true --scope project --confirm
```

User-level values do not authorize cleanup. Finalize never asks per session.
An unreadable config, missing project opt-in, or unresolved project fails safe
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
`warn_tokens`, `warn_seconds`, `require_answer_packet`, and
`report_promotions`. Each detected destination
project must separately set `[distill.autonomous].enabled=true`. A completed
row contains a formal Answer Packet and lists each promoted fact with its
destination project and category. Dry-run is read-only and does not consume the
daily ledger.

`project_scope` defaults to `current`; processing archives attributed to other
projects requires an explicit `all` scope. This is per-run scoping, not a
project allowlist.

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
