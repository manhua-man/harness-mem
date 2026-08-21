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
session evidence, auto-promote low-risk memory, use human `review` to correct
or undo it, and use Dream to discover stale, duplicate, conflicting, or
replaceable knowledge for another verification-and-assimilation pass.

Invocation surfaces (installed once at user scope, then visible in every project):

- `/hm:*` commands: `status`, `wake`, `search`, `search-all`, `distill`, `review`, `dream`.
- Agent MCP calls: plain language, skills, or hooks trigger `wake/search/distill/review`.
- Hooks: inject wake context, enforce retention, save an immutable session revision, and create or advance its job. A Hook then wakes Dream with that exact source reference; Dream, not the Hook, performs unattended session distillation and project governance through a no-tools provider. Missing provider/auth configuration remains explicit retryable work rather than a false completion.
- CLI: setup, doctor, config, integration, and maintenance only.

Everyday use reduces to three intents: continue work with `wake/search`, remember
a reusable result through the distill/governance path, or review/undo an
incorrect memory. Dream is a core governance-feedback capability, normally
triggered by the runtime rather than a checklist step the user must perform each
day; `status` is the diagnostic summary surface.

<p align="center">
  <img src="docs/assets/harness-mem-cold-start-flow.svg" alt="A fresh Agent uses wake, search, distill, review, and dream against a local auditable memory backend" width="900" />
</p>

## Architecture and daily actions

The product's internal functional architecture is not a list of daily commands:

```text
0. session intake and lifecycle
-> 1. extraction
-> 2. per-point verification
-> 3. assimilation
-> 4. retrieval/use
```

Stage 0 owns supported-host intake, authorization, immutable revisions,
lossless chunks, jobs, receipts, retries, and safe source retention/cleanup.
Stages 1--4 decide and use project knowledge. One session can yield zero to
twelve independent promotion points; verification and assimilation operate on
each point independently.

Dream and Review are core governance-feedback capabilities across stages 3--4,
not a linear sixth stage and not operator-only maintenance:

```text
4. retrieval/use -> useful / ignored / misleading / stale feedback
                  -> review / Dream -> re-verify -> assimilate
                  -> current long-term knowledge
```

Audit receipts cross every stage: intake receipt, extraction coverage,
verification evidence, assimilation/lineage decision, and retrieval feedback.

The user-facing actions map onto that architecture; they are not a replacement
for it:

| Action | Role |
|---|---|
| `wake` | Load a compact project brief from readable memory at session start. |
| `search` | Retrieve prior decisions, rules, and handoffs when `autopilot_search_tick` detects concrete uncertainty, conflict, tool failure, durable-claim grounding, or a long-horizon task switch. |
| `distill` | Orchestrate stages 1--3 over a completed Stage-0 session revision. |
| `review` | Core human governance feedback: audit, confirm, reject, undo, correct, or supersede knowledge and return it to verification/assimilation when needed. |
| `dream` | Core automated governance feedback: find stale, duplicate, conflicting, mergeable, or replaceable knowledge and route it through verification and assimilation. |
| `status` | Summarize actual state across stages 0--4. |

Hooks and archive maintenance belong to Stage 0. Raw
search/timeline, candidate detail, runtime reset, and storage repair are
explicit audit or operator capabilities; they do not define the long-term
knowledge model.

The released `0.9.25` runtime uses SQLite `knowledge_entries` as the authority
for clean current knowledge. Candidate, verification, and proposed decision
material is job-scoped and cleaned after a proven terminal outcome; legacy
`MemoryEntry` remains readable for compatibility. Current search reads SQLite
deterministically, while FTS/vector remain optional rebuildable optimizations.
Markdown is rendered only when a user asks to read or export the library.
Natural project modules are formed without a hard-coded module allowlist. A
frozen six-session acceptance passed. Any additional live legacy-memory
migration still requires separate explicit authorization. See
[SQLite Current-Knowledge Convergence](docs/roadmap/knowledge-truth-separation.md).

The runtime search scheduler is event-driven, not always-on. PI-style
`transformContext`, `tool_result`, and `prepareNextTurn` events map directly to
`autopilot_search_tick`; Claude Code `PostToolUse` and Cursor after-agent hooks
can send the same event payload shape. `/hm:search` remains the manual fallback
when a client cannot expose those hooks. A Stop hook only saves an immutable
native transcript revision, creates or advances its job, and emits a
source-bound Dream activity signal. It never performs semantic judgment.

There are two execution paths. An explicit `/hm:distill` stays in the current
host: it reads every ordered chunk and evidence window without truncating them,
extracts promotion points, verifies them, and lets trusted runtime assimilation
update only proven current knowledge. `finalize_session_distill` is the commit
point for that explicit job; it never starts Dream. A
Hook-started Dream is the only unattended executor: after a project explicitly
selects an operator-owned provider profile and enables autonomous execution, it
reopens the triggering session and the project's current knowledge, sources,
and feedback. Dream then extracts or compares, verifies, assimilates, and ends
each item as applied, rejected, archived, or failed/retryable.

Provider profiles contain only a protocol, endpoint, model, timeout, and an
environment-variable name in user configuration; project configuration can
only select a named profile. The provider is a no-tools, strict-schema semantic
call. It cannot access project files or credentials directly, and trusted
runtime code remains the only writer of candidates, Session Notes, and SQLite
truth. `/hm:review` is the separate post-hoc correction and undo surface, not a
promotion gate. The Hook can claim only that work was queued; unattended work
can claim completion only after its terminal receipt and Note materialize.
Legacy Observations without an available native transcript remain audit-only
(`legacy_partial`).

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
Successful distill retains the original source by default. Source cleanup is
allowed only when the project explicitly enables it and the adapter supports
session-scoped deletion with passing quiet/CAS/hash checks:

```bash
harness-mem config set distill.delete_source_after_complete true --scope project --confirm
```

User-level values do not authorize this destructive policy. If config is
unreadable, the project value is absent, or the project cannot be resolved,
completion fails safe and retains the source. When enabled, completed jobs delete an eligible quiet native session source,
local raw bytes, chunks, checkpoint results, matching Observations, and derived
indexes while retaining governed long-term knowledge in canonical SQLite. Every
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
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.25 \
  harness-mem==0.9.25
```

`harness-mem` itself is distributed through GitHub Releases. The command above
selects the compatible native wheel for Windows, macOS, or Linux; no PyPI
project or account is required.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.25 \
  "harness-mem[hybrid]==0.9.25"
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

Unattended Dream processing requires a project-scoped authorization. A Stop Hook
only saves the immutable session revision, creates or advances its job, and
wakes Dream. Dream then processes that session and project-level knowledge in
the background, using the configured provider and consuming its quota:

```bash
harness-mem config set distill.autonomous.enabled true --scope project --confirm
```

The global default is `false`. Projects without this authorization keep captured
jobs queued for explicit processing. An explicit `distill` stays in the active
host, for example Codex when you ask Codex to process a Codex archive; it is not
silently sent to the background profile. Disabling never requires confirmation.

Version `0.9.25` supports an operator-owned
restricted provider profile for unattended Dream, including Hook-started session
distillation and project source rechecks. Keep the endpoint and environment-variable reference in the user
configuration (never in a repository), then select that already approved
profile for one authorized project:

```toml
# ~/.harness-mem/config.toml
[semantic.providers.local-gateway]
protocol = "anthropic-messages" # or "openai-responses"
base_url = "https://gateway.example/v1"
api_key_env = "HARNESS_MEM_GATEWAY_KEY"
model = "operator-approved-model"
output_mode = "json" # default: "tool"; use for gateways that reject forced output tools
thinking_mode = "disabled" # use when a reasoning gateway returns thinking but no final JSON text
```

```bash
harness-mem config set semantic.execution.profile local-gateway --scope project
```

The profile has no access to Agent tools, MCP, the filesystem, or host rules;
it returns only the required structured semantic decision. `output_mode = "json"`
is a no-tool compatibility channel for gateways that reject forced output tools:
non-JSON or schema-invalid text fails closed. For an Anthropic-compatible
reasoning gateway that returns only a thinking block, `thinking_mode =
"disabled"` requests a final JSON response instead. A selected profile does not
authorize model calls on its own: the project must also have
`distill.autonomous.enabled=true`.

For archived Codex tasks, first bind the project root. The default
`archive_distill.project_scope = "current"` processes only that project;
cross-project processing requires an explicit `all` scope. Preview before
running one policy-bounded batch:

```bash
harness-mem maintenance archive-distill --dry-run --project-root .
harness-mem maintenance archive-distill --apply --verify --json --project-root .
```

`[archive_distill]` controls enablement, batch and daily limits, ordering,
unresolved-project handling, token/latency warnings, mandatory
Answer Packets, and per-item promotion reporting. The formal Answer Packet
records the original question, verified conclusion and evidence, promotion
status, target project/category, and every promoted fact. Runtime-only tuning
remains read-only and can be inspected with
`harness-mem config list --detail runtime`.

`--verify` reuses the same initialized backend and emits one run-bound receipt
covering persisted jobs and Answer Packets, Notes, daily-ledger replay guards,
promoted-truth retrieval, and source-cleanup audit. Exact-output smoke sessions
are deterministically classified as non-durable without calling the model.

Verified terminal state is durable across UTC days and keyed to the exact source
revision, so a retained archive is not sent to the provider again. A completed
partial receipt can be read back without model work, including after verified
cleanup removed the native source:

```bash
harness-mem maintenance archive-distill --apply --verify --repair-only --project-root .
```

For a one-time drain, `--batch-size` and `--daily-limit` override only that run;
project defaults stay unchanged. Apply runs remain single-process because the
transcript store, completion index, receipts, and cleanup path share one exclusive
maintenance lock. Stop on any non-passed verification. A completed job is repaired
by read-back, while an incomplete job receives at most one further semantic attempt
before it is quarantined with the source retained. Terminal reports conserve all
sessions as verified, pending, quarantined, deferred-unresolved, or excluded.

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
- `code/plugins/harness-mem/`: Agent client integration.
- `code/tools/hm-distill/SKILL.md`: instruction-only Agent playbook for the supported MCP distill flow; runtime code lives exclusively under `harness_mem/`.
- `docs/quickstart.md`: minimal setup path.
- `docs/mcp-setup.md`: MCP setup notes.
- `docs/demo-cold-start.md`: reproducible cold-start demo.
- `docs/assets/`: logo and public README diagrams.
- [项目结构收敛说明](docs/project-structure.md):源码与文档一体化布局说明（不含运行时变更）。
- 一次性清理脚本：
  - `scripts\\clean-workspace.ps1 clean`（保守清理：临时缓存）
  - `scripts\\clean-workspace.ps1 clean-all`（强清：保守缓存 + 构建产物）

## Documentation

- [Quickstart](docs/quickstart.md)
- [IDE hook adapter matrix](docs/ide-hook-adapter-matrix.md)
- [MCP setup](docs/mcp-setup.md)
- [Cold-start demo](docs/demo-cold-start.md)
- [Recall audit contract](docs/recall-audit.md)
- [Distill acceptance test plan](docs/distill-test-plan.md)
- [Autopilot search policy](docs/autopilot-search-policy.md)
- [Compatibility inventory](docs/compatibility-inventory.md)
- [Reference-project evidence index](docs/reference-projects/index.md)
- [Agent memory & retrieval research (2026)](docs/agent-memory-retrieval-research-2026.md)
- [Roadmap](docs/roadmap.md)
- [Changelog](CHANGELOG.md)

## Development Check

```bash
python -m compileall harness_mem
python -m ruff check harness_mem code/plugins code/tools
python -m mypy harness_mem
python -m pytest -q code/tests/test_package_version_alignment.py code/tests/test_version_drift.py  # run first after a version bump
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
python code/tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

The verifier takes an exclusive lock per output path and atomically publishes the
final report, so a second run cannot overwrite evidence from one already in
progress. Reports include a run ID and per-check timing. For a bounded diagnostic
read without the full Note inventory, select only the needed outcome section:

```bash
python -m harness_mem.outcome_probe \
  --project harness-mem \
  --project-root . \
  --client codex \
  --section autonomous \
  --compact
```

IDE hooks remain non-blocking. A human or Agent can explicitly wait for a
background post-turn receipt by piping the real Codex Hook payload (it must contain
`session_id` or `turn_id`):

```powershell
'{"session_id":"<codex-session-id>"}' |
  harness-mem-hook --adapter codex-stop --project-root . --wait --wait-timeout 120
```

The command binds the wait to both the Hook identity and this dispatch generation.
It returns terminal JSON and a non-zero exit code for missing identity, an error-bearing
receipt, deferred, failed, or timed-out work. Calling `--wait` without a Hook identity
fails immediately instead of waiting for an unbindable receipt.

This read-only probe requires fresh paired Codex lifecycle receipts, a persisted
successful Dream run, a meaningful Note and semantic summary for every recent
completed distill session, and a durable truth that can be returned through the
FTS read model. A non-zero verdict means the user-visible outcome is not complete,
even when code, configuration, queues, or unit tests look healthy.

Repair or regenerate MCP descriptors when `tool_specs` changes (also reverts incidental `code/mcps/grok_com_github` IDE drift):

```bash
python code/scripts/ensure_mcps_canonical.py
```

## Releases

- Package version is pinned in `pyproject.toml` and summarized here after each release.
- Tag pushes matching `v*` run [`.github/workflows/release-wheels.yml`](.github/workflows/release-wheels.yml), which builds six native wheels and an sdist, verifies fresh installs on Windows/macOS/Linux, runs a real sqlite-vec contract gate, qualifies the supported Windows upgrade path, and attaches the distributions to the GitHub Release. The project does not publish to PyPI.

Current package version: **0.9.25**.
