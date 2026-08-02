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
- Hooks: inject wake context, enforce retention, and maintain a two-job Agent-active distill lane with 3:1 recent/oldest refill, failure backoff, and a daily new-job budget. Without an Agent the queue reports `waiting_for_agent`; it never claims background semantic work.
- CLI: setup, doctor, config, integration, and maintenance only.

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
| `distill` | Verify every ordered raw chunk, read a ≤3k-token indexed manifest, select complete semantic windows, drill into candidate-grade raw proof, then run end-of-session review, governance, and Dream. |
| `review` | Audit, confirm, reject, undo, or supersede auto-promoted and pending items after the fact. |
| `dream` | Maintain the ledger, compact stale state, and keep reversible cleanup metadata current after save points or session end. |

The runtime search scheduler is event-driven, not always-on. PI-style
`transformContext`, `tool_result`, and `prepareNextTurn` events map directly to
`autopilot_search_tick`; Claude Code `PostToolUse` and Cursor after-agent hooks
can send the same event payload shape. `/hm:search` remains the manual fallback
when a client cannot expose those hooks. Stop hooks capture an immutable native
transcript revision and queue its complete ordered chunk set. Daily
`prepare_session_distill(evidence_mode="semantic", detail_level="compact",
budget_tokens=3000)` keeps the raw revision intact, hash-verifies and checkpoints
every chunk, then returns an indexed exchange manifest. The Agent selects up to
eight complete semantic windows and only then drills into candidate-grade raw
proof. `detail_level="full"` and the compatible `raw` mode remain explicit audit paths; raw mode claims bounded
chunks without truncating them for explicit deep audit. The Agent performs an
end-of-session review and only then creates idempotent candidates. `finalize_session_distill` runs
automatic governance and Dream, records `promoted` or `no_candidate`, and
terminally rejects non-promoted candidates so low-value sessions do not become
recurring manual work. `/hm:review` remains the correction and undo surface,
not a required promotion gate. `/hm:distill` is the immediate entry to this same
resumable pipeline. Hook maintenance only captures and queues evidence: it does
not claim that an Agent has already summarized the session. Legacy Observations
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
config is limited to ten durable policy choices while older tuning values stay
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
project status preserves the decisions while full drilldown adds seven-day
retrieval outcome/abstention/exclusion counts and concrete distill backlog
reasons plus a conservative Agent-throughput drain estimate.
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
- Pluggable: use it from Codex, Claude Code, Cursor, Gemini CLI, or any MCP-capable Agent client.

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
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.9 \
  harness-mem==0.9.9
```

`harness-mem` itself is distributed through GitHub Releases. The command above
selects the compatible native wheel for Windows, macOS, or Linux; no PyPI
project or account is required.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.9 \
  "harness-mem[hybrid]==0.9.9"
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
`harness-mem integration hooks sync --client <host> --project-root . --force`.

Codex applies an additional native security gate to project command hooks.
After automatic installation, open **Codex Settings > Hooks**, review and trust
the new project hooks once, then start a new task. Until a matching
`SessionStart` hook has actually completed, `get_project_status` reports
`hooks=review_required` rather than claiming wake is operational.

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
- `tools/session-distill/SKILL.md`: instruction-only Agent playbook for the supported MCP distill flow; runtime code lives exclusively under `harness_mem/`.
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
- [Memory adoption: optional helpers (analysis)](docs/memory-adoption.md)
- [Agent memory & retrieval research (2026)](docs/agent-memory-retrieval-research-2026.md)
- [Roadmap](docs/roadmap.md)
- [Changelog](CHANGELOG.md)

## Development Check

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m mypy harness_mem
python -m pytest -q
python -m harness_mem.cli --help
cargo test --workspace
```

Repair or regenerate MCP descriptors when `tool_specs` changes (also reverts incidental `mcps/grok_com_github` IDE drift):

```bash
python scripts/ensure_mcps_canonical.py
```

## Releases

- Package version is pinned in `pyproject.toml` and summarized here after each release.
- Tag pushes matching `v*` run [`.github/workflows/release-wheels.yml`](.github/workflows/release-wheels.yml), which builds six native wheels and an sdist, verifies fresh installs on Windows/macOS/Linux, runs a real sqlite-vec contract gate, qualifies the supported Windows upgrade path, and attaches the distributions to the GitHub Release. The project does not publish to PyPI.

Current package version: **0.9.9**.
