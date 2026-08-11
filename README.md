<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem logo" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center">
  <strong>Local-first, auditable, pluggable memory backend for AI Agents.</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="public smoke status" />
  </a>
</p>

AI Agents can read your repo, but they usually do not know what happened in the
last ten sessions: release boundaries, decisions, handoffs, review outcomes,
and "do not claim this yet" rules.

`harness-mem` turns that project memory into a local backend exposed through
one MCP memory surface. Claude Code, Codex, Cursor, Grok, Hermes, OpenCode, and
Antigravity recover context with `wake` and task-aware `search`, distill recent
session evidence, auto-promote low-risk memory, keep human review as a
post-hoc audit/undo surface, and let dream maintain the ledger.

Invocation surfaces (installed once at user scope, then visible in every project):

- `/hm:*` commands: `status`, `wake`, `search`, `search-all`, `distill`, `review`, `dream`.
- Agent MCP calls: plain language, skills, or hooks trigger `wake/search/distill/review`.
- Hooks: inject wake context, enforce retention, and dispatch a detached autonomous distill worker. The exact Stop session gets the first slot; one bounded backlog slot then follows the 3:1 recent/oldest refill and daily backlog budget. Each job runs through a no-tools Structured Output provider with review leases and failure backoff. Missing provider/auth configuration remains explicit retryable work rather than a false completion.
- CLI: setup, doctor, config, integration, and maintenance only.

Everyday use reduces to three intents: continue work with `wake/search`, remember
a reusable result through the distill/governance path, or review/undo an
incorrect memory. Status and Dream remain compatible diagnostics and maintenance,
not extra steps the user must manually perform every day.

<p align="center">
  <img src="docs/assets/harness-mem-cold-start-flow.svg" alt="A fresh Agent uses wake, search, distill, review, and dream against a local auditable memory backend" width="900" />
</p>

## Core Loop

```text
wake -> search -> distill -> review -> dream
```

| Step | Job |
|---|---|
| `wake` | Load a compact project brief from readable memory at session start. |
| `search` | Retrieve prior decisions, rules, and handoffs when `autopilot_search_tick` detects concrete uncertainty, conflict, tool failure, durable-claim grounding, or a long-horizon task switch. |
| `distill` | Verify every ordered raw chunk, read a coverage-first indexed manifest under an adaptive complete-response target, select complete semantic windows, drill into candidate-grade raw proof, then run end-of-session review, governance, and Dream. |
| `review` | Audit, confirm, reject, undo, or supersede auto-promoted and pending items after the fact. |
| `dream` | Maintain the ledger, compact stale state, and keep reversible cleanup metadata current after save points or session end. |

The runtime search scheduler is event-driven, not always-on. PI-style
`transformContext`, `tool_result`, and `prepareNextTurn` events map directly to
`autopilot_search_tick`; Claude Code `PostToolUse` and Cursor after-agent hooks
can send the same event payload shape. `/hm:search` remains the manual fallback
when a client cannot expose those hooks. Stop hooks capture an immutable native
transcript revision and queue its complete ordered chunk set. Daily
`prepare_session_distill(evidence_mode="semantic", detail_level="compact")`
keeps the raw revision intact, hash-verifies and checkpoints every chunk, then
returns an indexed exchange manifest. Its budget is a caller-configurable soft
target for the complete serialized MCP response, not a fixed 3k limit. Every
exchange remains indexed; if coverage or explicit drilldown needs more space,
`response_budget` reports the actual token count and expansion reason. The Agent selects up to
eight complete semantic windows and only then drills into candidate-grade raw
proof. `detail_level="full"` and the compatible `raw` mode remain explicit audit paths; raw mode claims bounded
chunks without truncating them for explicit deep audit. The Agent performs an
end-of-session review and only then creates idempotent candidates. Detected
decision, solution, preference, workflow, migration, or handoff signals start
fail-closed as `candidate_required`; downgrading one requires its complete
window plus a signal-specific session-only explanation. `finalize_session_distill`
runs scoped automatic governance, records `promoted` or `no_candidate`, and
terminally rejects non-promoted candidates so low-value sessions do not become
recurring manual work. Answered candidates can still promote when unrelated
unfinished work is recorded as a scoped handoff, but Dream waits for a fully
completed review. Readable results and Session Notes show a title, one verifiable
fact, and verification date/status; internal IDs stay in explicit audit detail.
The detached Hook worker consumes the same semantic manifest through the
configured Responses endpoint with no tools, no project filesystem access,
`store=false`, and a strict response schema. It owns a renewable review lease,
then lets trusted runtime code create candidates, finalize the job, and
atomically materialize `~/.codex/hm-distill/sessions/<session-id>.md`. Health
persists actual provider tokens and duration plus `last_semantic_success_at`,
`last_job_completed_at`, and `last_note_materialized_at`. The non-interactive
Codex CLI provider remains a compatibility fallback, not the default worker.
`/hm:review` remains the correction and undo surface,
not a required promotion gate. `/hm:distill` is the immediate entry to this same
resumable pipeline. The synchronous Hook only captures and queues evidence; its
detached worker may claim completion only after finalize and Note materialization
receipts exist. Legacy Observations
without an available native transcript remain audit-only (`legacy_partial`).

New distill candidates carry an evidence basis and verification outcome.
Repository facts must point to a current project-relative file digest; explicit
preferences and decisions point to a user-authored exchange digest.
Transcript-only, missing, changed, or contradicted evidence cannot become
durable truth. Relation facts use the same policy, and legacy truth is not
retroactively reclassified.

Version 0.9.6 converged the installed surface without changing that workflow:
the MCP schema, handler, cluster, and descriptor registries now contain exactly
the same 27 public tools; hook repair has one cross-host command; and public
config is limited to eleven durable policy choices while older tuning values stay
readable for compatibility.

Version 0.9.9 hardens that surface rather than adding another product path:
bounded restart recovery, atomic derived-index rebuilds, seven-host native
replay, and install/upgrade/restore qualification all use the existing local
SQLite, Adapter, Dream, and Doctor boundaries. Detailed replay metrics remain
maintenance artifacts; everyday wake, status, and distill responses stay
compact.

Observations are evidence, never remembered facts. Wake labels their recent
index as non-truth; L1/L2 contain only structured current facts and active
handoffs. Version or release claims contradicted by the current repository are
marked stale or withheld from truth layers.

Privacy is enforced before persistence. Put sensitive spans inside
`<private>...</private>`, or configure project-level `[capture]` ignore lists;
excluded content never reaches raw revisions, chunks, Observations, or indexes.
`[transcript].retention_days` enables automatic expiry (`0` keeps data).
Processed source deletion is a separate persistent opt-in and defaults off:

```bash
harness-mem config set distill.delete_source_after_complete true --scope user --confirm
```

`--confirm` is required only for the persistent transition from disabled to
enabled; disabling the policy and individual completed sessions require no
extra prompt. In an IDE, the explicit natural-language instruction “enable
harness-mem deletion of original sessions after distill” authorizes the Agent
to perform this confirmed config write. When enabled, completed jobs delete an eligible quiet native session source,
local raw bytes, chunks, checkpoint results, matching Observations, and derived
indexes while retaining sanitized durable Memory/Rule/Fact/Skill truth. Every
attempt reports `retained`, `deleted`, `partial_failure`, or `unsupported` and
writes a content-free receipt before native mutation. Shared SQLite/JSONL
containers that lack a safe transactional session deleter are left untouched
and reported as unsupported; no whole shared history file is ever unlinked.
`harness-mem maintenance erase --project NAME --session-id ID` previews a full
hard delete; add `--apply` to erase raw revisions, chunks, jobs, Observations,
linked candidates/truth, FTS/vector rows, and eligible native host session
files. Apply first persists a content-free receipt, then runs bounded native
CAS deletion and the internal reference-closure delete. Unsafe or shared native
containers remain untouched and make the result a partial failure; receipt
failure prevents deletion, and partial deletion returns a non-zero status.

Operational diagnosis is equally explicit. Doctor probes SQLite read-only and
renders a recovery plan grouped as `safe_rebuild`, `snapshot_required`,
`manual_review`, or `destructive`; it never auto-applies a repair. Compact
project status preserves the decisions while full drilldown adds the
content-free captured-to-feedback funnel, including explicit
`missing_feedback`, retrieval outcome/abstention/exclusion counts, concrete
distill backlog reasons, and a conservative Agent-throughput drain estimate.
Legacy entity JSON is deprecated in 0.9.6 but supported through 0.9.x; it will
not be removed before both 1.0.0 and 2027-01-31. Existing legacy-only stores
stay readable without silently changing authority. See
[legacy storage lifecycle](docs/storage-legacy-lifecycle.md).

<p align="center">
  <img src="docs/assets/harness-mem-lossless-session-flow.svg" alt="Native IDE transcripts are preserved as immutable revisions, processed through every ordered chunk, reviewed at session end, and only then promoted into memory" width="900" />
</p>

## Why It Is Different

- Local-first: project memory stays on your machine by default.
- Agent-ready: MCP is the normal integration path for coding tools.
- Reviewable: low-risk memory can be auto-promoted, while risk, evidence, and undo metadata stay auditable.
- Pluggable: use it from Claude Code, Codex, Cursor, Grok, Hermes, OpenCode,
  Antigravity, or another MCP-capable Agent client.

<p align="center">
  <img src="docs/assets/harness-mem-candidate-governance.svg" alt="candidate-before-truth memory governance state machine" width="900" />
</p>

`harness-mem` stays behind the Agent client. MCP is the transport; the runtime
owns storage, candidates, review, retrieval, and local audit state.

<p align="center">
  <img src="docs/assets/harness-mem-runtime-layered-architecture.svg" alt="harness-mem runtime layered architecture" width="900" />
</p>

## Install

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.11 \
  harness-mem==0.9.11
```

`harness-mem` itself is distributed through GitHub Releases. The command above
selects the compatible native wheel for Windows, macOS, or Linux; no PyPI
project or account is required.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.11 \
  "harness-mem[hybrid]==0.9.11"
```

Install every supported host's native Daily commands once for the current
device. The default is `--client all --scope user`:

```bash
harness-mem integration commands sync
```

This writes only harness-mem command, skill, or workflow files under each
host's user-level discovery directory. It does not install project hooks or
bind one project path into the global files.

Claude Code users can install the repo-local plugin and optionally register MCP:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

For Cursor, register a project-scoped MCP server that runs from the workspace:

```json
{
  "command": "harness-mem-mcp",
  "cwd": "${workspaceFolder}",
  "env": {
    "HARNESS_MEM_CLIENT": "cursor"
  }
}
```

`harness-mem-mcp` is installed with the package and launches the MCP server
from that exact package environment. Run `harness-mem-mcp` once in a terminal
to verify that the command is on `PATH`. If Cursor does not inherit that PATH,
use the absolute path reported by `where harness-mem-mcp` (Windows) or
`which harness-mem-mcp` (macOS/Linux) as `command` instead of `python`.

On first MCP initialization, harness-mem adopts the workspace, creates its
project profile, installs the matching project hooks without overwriting
existing files, and idempotently repairs the current host's user-level command
surface. Users do not run a per-project command or hook installer. See
[docs/ide-hook-adapter-matrix.md](docs/ide-hook-adapter-matrix.md) for the
current adapter surface and install model for each host.

For explicit operator repair, use the one cross-host path:
`harness-mem integration hooks sync --client all --project-root . --force`.
Replace `all` with one host name when only that integration needs repair.

Codex applies an additional native security gate to project command hooks.
After automatic installation, open **Codex Settings > Hooks**, review and trust
the new project hooks once, then start a new task. Until a matching
`SessionStart` hook has actually completed, `get_project_status` reports
`hooks=review_required` rather than claiming wake is operational.

Autonomous semantic processing requires one separate persistent authorization
because it sends the compact manifest to the configured model provider and may
consume quota. Enable it once at user scope; future Stop turns do not ask again:

```bash
harness-mem config set distill.autonomous.enabled true --scope user --confirm
```

Set the value to `false` at user or project scope to return to queue-only Hook
behavior. Disabling never requires confirmation.

The repo installer performs the same all-host user-level sync automatically:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

All supported hosts expose the same actions: `status`, `wake`, `search`,
`search-all`, `distill`, `review`, and `dream`. Claude Code uses
`/hm:<action>`; Codex uses user-invocable `$hm-<action>` skills; Cursor, Grok,
Hermes, OpenCode, and Antigravity use `/hm-<action>`. Codex cannot register
custom slash commands, so `$hm-*` is its native command form.
The user-global locations are Claude Code `~/.claude/commands/hm`, Codex
`~/.codex/skills`, Cursor `~/.cursor/skills`, Grok `~/.grok/skills`, Hermes
`$HERMES_HOME/skills` (`%LOCALAPPDATA%/hermes/skills` on native Windows),
OpenCode `~/.config/opencode/commands`, and Antigravity
`~/.gemini/antigravity/global_workflows`.
The generated commands resolve MCP tools by logical name. Direct
`harness_mem` connections and MCP Router connections may expose different
internal prefixes; users keep invoking the same host-native command. Restart
the MCP server and open a new task after a registration or tool-schema change.

`codex-archive` is a backward-compatible source identifier for archived Codex
rollouts, not an eighth host. Old configuration and stored source records remain
readable, while capability, status, and qualification counts group the alias
under Codex.

The terminal CLI is an operator console, not the daily memory workflow. Its
top-level surface is `init`, `quickstart`/`qs`, `doctor`, `config`,
`integration`, and `maintenance`. Import and purge operations live under
`harness-mem maintenance ...` and default to dry-run previews.
Other CLI maintenance actions stay limited to operator repair and audit tasks
such as index rebuilds, storage migration/export, and state audit.
Procedural skill lifecycle management is outside the public memory MCP and CLI
product surface.

## Repository

- `harness_mem/`: runtime package.
- `plugins/harness-mem/`: Agent client integration.
- `tools/hm-distill/SKILL.md`: instruction-only Agent playbook for the supported MCP distill flow; runtime code lives exclusively under `harness_mem/`.
- `docs/quickstart.md`: minimal setup path.
- `docs/mcp-setup.md`: MCP setup notes.
- `docs/demo-cold-start.md`: reproducible cold-start demo.
- `docs/assets/`: logo and public README diagrams.

## Documentation

- [Quickstart](docs/quickstart.md)
- [IDE hook adapter matrix](docs/ide-hook-adapter-matrix.md)
- [MCP setup](docs/mcp-setup.md)
- [Cold-start demo](docs/demo-cold-start.md)
- [Recall audit contract](docs/recall-audit.md)
- [Autopilot search policy](docs/autopilot-search-policy.md)
- [Compatibility inventory](docs/compatibility-inventory.md)
- [Reference-project evidence index](docs/reference-projects/index.md)
- [Agent memory & retrieval research (2026)](docs/agent-memory-retrieval-research-2026.md)
- [Roadmap](docs/roadmap.md)
- [Changelog](CHANGELOG.md)

## Development Check

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m mypy harness_mem
python -m pytest -q -m "not release_gate"  # fast PR lane
python -m pytest -q                        # complete release lane
python -m harness_mem.cli --help
cargo test --workspace
```

The fast lane skips only four exhaustive, deterministic 60-case retrieval
replays. Every assertion still runs on `main` and in the tagged release gate.

Before claiming that the running product is complete, execute the repository's
user-outcome contract with the cross-project `outcome-verifier` Skill:

```bash
python tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

This read-only probe requires fresh paired Codex lifecycle receipts, a persisted
successful Dream run, a meaningful Note and semantic summary for every recent
completed distill session, and a durable truth that can be returned through the
FTS read model. A non-zero verdict means the user-visible outcome is not complete,
even when code, configuration, queues, or unit tests look healthy.

Repair or regenerate MCP descriptors when `tool_specs` changes (also reverts incidental `mcps/grok_com_github` IDE drift):

```bash
python scripts/ensure_mcps_canonical.py
```

## Releases

- Package version is pinned in `pyproject.toml` and summarized here after each release.
- Tag pushes matching `v*` run [`.github/workflows/release-wheels.yml`](.github/workflows/release-wheels.yml), which builds six native wheels and an sdist, verifies fresh installs on Windows/macOS/Linux, runs a real sqlite-vec contract gate, qualifies the supported Windows upgrade path, and attaches the distributions to the GitHub Release. The project does not publish to PyPI.

Current package version: **0.9.11**. It includes the context-lineage work
previously documented as 0.9.10; no separate 0.9.10 package or tag was published.
