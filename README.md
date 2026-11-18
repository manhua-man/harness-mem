<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem logo" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center"><strong>A local memory engine for AI Agents.</strong></p>

<p align="center"><a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="public smoke status" />
  </a>
</p>

Your Agent can read the repository, but it does not automatically retain what
mattered in earlier conversations or what still needs attention. `harness-mem`
keeps useful knowledge locally so Agents can recall and correct it, without
asking you to manage projects or directories.

The current development priority is **finished conversations → verified,
organized knowledge → processed-history cleanup → useful recall**. The current
Agent performs historical organization through the existing MCP tools; lifecycle
Hooks, a background model and Dream are not prerequisites. Use the native `hm`
command with fixed actions: `distill --project <name>`, `continue`, and
`clean --apply`; `distill --cleanup` authorizes cleanup after successful review.
Cleanup previews the frozen selection before explicit execution and keeps
active, changed or unresolved sources. This workflow is being implemented and
evaluated against [session-distill-skills](https://github.com/manhua-man/session-distill-skills);
it is not yet fully accepted or included in release 0.9.28. See the
[current plan and evidence](docs/roadmap.md#current-iteration-plan). Automatic
per-turn recording and host injection are deferred during this work; the local
runtime remains uninstalled. The release setup below does not enable or validate
the unreleased workflow.

The unreleased working tree supports one selected-device batch across sessions
with different, missing or absent workspace directories. Directories are optional
context, not intake prerequisites. Per-point verification, SQLite writes and
ordinary-search readback remain required. Installation does not process old sessions.

Unreleased working-tree intake improvements retain short sessions by default.
Cursor supports exported JSONL and read-only native SQLite inspection covered
by isolated fixtures; this does not establish support for every live database
format. Blank sources, unreadable files and completed organization are distinct.

In the unreleased working tree, an organization result includes the saved
knowledge itself, not only its count. Use `hm review` to read current knowledge;
ordinary searches stay compact. You can optionally
ask for one project's knowledge grouped by module.

The current source provides on-demand, version-checked Codex tool records from
the prepared conversation. These records supplement the conversation and cannot
be used as user-authored evidence. Source reports display a concise attribution,
their native session time and complete conditions; ordinary search results can
still be used directly to select a memory for correction.

The unreleased reading update supports continuation; the Agent reads all pages
when asked to show all memory, and long entries remain available in full.
Without a task, the automatic startup Hook suggests a focused search instead of
opening the whole library; explicit MCP `wake` can still show availability.
Task-aware automatic recall returns incomplete keyword candidates for the current
Agent to assess and open. Long Chinese requests and some named-subject compound
searches also show candidates; other short searches may return whole facts
directly, or `detail="candidates"`
can be used to review them first. For missing context the Agent can search each
unanswered aspect with focused terms and consider applicable cross-project or
global rules. Candidate previews can still distract or miss useful memory and
are not verified relevance. Identical wording in different projects retains
each project identity; check the complete fact for its actual scope.
Response size uses the existing wake/search settings and counts the complete
output, including automatic-recall feedback.

Manual searches with explicit task context use cost-aware `auto` output: a
complete entry is returned directly when it costs less than its preview link.
The Agent reuses complete statements and opens only previews, keeping the same
page budget and all stored conditions. Explicit candidate-only mode is retained.

The approved unreleased default is recall across **all projects**: ordinary
search, session-start `wake`, and automatic task-aware search use current
SQLite knowledge without locking recall to the active workspace. Project
information is optional context or an explicit filter. Raw conversations,
job material and legacy rows remain excluded. Current source and live MCP
inventory/search/wake checks passed on 2026-10-12. Published `0.9.28` does
not include this default change.

The unreleased source restores explicit historical organization through `hm distill`, `hm status`, and `hm continue`. The Agent discovers existing batches and follows returned references; users do not manage IDs. A pause requires explicit continuation. Manual work in the current Agent needs no background CLI authorization. Shared writing checks actual final titles, bodies, report attribution and conditions retained by corrections.

Background task budgets cover native executor invocations dispatched by this runtime across source processing, Dream slices and retries under one maintenance task identity. Defaults are 64 invocations, 3,600 cumulative native seconds, 2,000,000 input tokens and 128,000 output tokens. Actual terminal usage is accumulated and checked before subsequent dispatch; the final invocation may cross a token threshold and may contain multiple model responses. Unknown usage blocks later invocations. These thresholds do not cap returned context, total user wait or the current Agent conversation. An explicit `task_model_budget.host_max_output_tokens` requests strict native bounds; unsupported or unproved bounds refuse before transport. Ordinary background execution does not require this optional hard cap. Local installation and readiness have fresh receipts; natural semantic acceptance remains pending. See [convergence status](docs/memory-write-convergence-20261020.md).

## Released setup and optional automation

Install the release with this single-line command in PowerShell, Command Prompt, or Bash:

```text
python -m pip install --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.28 harness-mem==0.9.28
```

Run this once for each Agent app you actually use. You do not rerun it for every
project:

```bash
harness-mem quickstart --confirm
```

Quickstart detects the current app. It can identify Codex and Claude Code directly.
If it cannot identify the current app, it stops and asks you to run it once with `--client`, for example
`harness-mem quickstart --client cursor --confirm`; it never installs another app's files
by guessing. In the unreleased development tree, it installs the global `$hm`
or `/hm` entry and user-level lifecycle Hooks, then `--confirm` authorizes
background model processing once. Hooks derive the workspace from each native
task, so new projects do not need another setup. Explicit project settings take
precedence; `distill.autonomous.enabled=false` opts a project out. Without
`--confirm`, Quickstart leaves background authorization unchanged. It does not
import historical sessions or inspect or change MCP settings.
Codex users must review and trust the user Hooks in **Settings > Hooks** once,
then start a new task. Hermes also requires native confirmation of its shell
Hooks on first use; Quickstart does not write the Hermes allowlist. Complete
the selected host's native review or confirmation before daily use. If
harness-mem tools are unavailable, ask the Agent,
MCP Router, plugin, or existing setup tool that manages your MCP connection to
connect harness-mem using [MCP setup](docs/mcp-setup.md). Do not add a second
connection when a Router or plugin already provides it. Installation and
authorization do not by themselves prove that native Hooks have executed.

All seven supported hosts remain product targets, not just Codex. Unreleased
Hook repairs register Claude Code/Cursor events and pass native session IDs
through Claude Code, Cursor, Grok and OpenCode. See the
[adapter matrix](docs/ide-hook-adapter-matrix.md) for requirements and the
separate fixture versus live-application evidence.
The package is distributed through GitHub Releases, not PyPI.

For optional local vector or hybrid search, install `"harness-mem[hybrid]==0.9.28"`
from the same release index. For the complete setup and host-specific exception,
see [Quickstart](docs/quickstart.md).

## Optional automatic memory and human review

After automatic integration is enabled, keep using your Agent normally. New
conversations are captured and useful knowledge is organized in the background;
relevant current memory is recalled as tasks need it. You do not ask to remember
each session or manage processing batches.

Use the native entry when you want to inspect or review memory:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Use fixed subcommands. Codex examples (replace `$hm` with `/hm` in other hosts):

```text
$hm help
$hm distill --project oiioii-studio --cleanup
$hm search "Oii upstream models and local alternatives"
$hm clean --project oiioii-studio --apply
$hm review --replace "<old title or text>" --with "<new text>"
$hm review --delete "<old title or text>"
```

Bare `hm` or `help` displays command help only. `distill` requires a named project
or explicit `--all`. `--cleanup` authorizes cleanup of that successfully reviewed
selection; standalone `clean` previews and `clean --apply` executes. `search`
defaults to all projects; only `--project-only <name>` restricts it. Missing or
unknown arguments show usage before work starts. These are Agent command
instructions, not new terminal CLI subcommands; native dispatch remains to be
verified after the user restores the currently uninstalled integration.

Manual review can bind each knowledge claim and its retained conditions to
exact passages in the reviewed source. Cleanup accounts for each selected
revision with retained output checks, planned native targets or record sets,
and available execution results. A completed review with zero knowledge writes
can qualify when its Note, source version and the existing cleanup checks pass.

Pass readable titles, topics or text as command arguments; you do not supply,
copy or manage memory IDs. The Agent finds the target across current memory, then
verifies its stored context and tool-returned references before changing it;
it must not guess IDs. If the supplied title or text
do not identify one target uniquely, it keeps the existing memory and explains
what it cannot determine using readable titles or content.

One failed or ambiguous item must not prevent other independent, verified
content from being saved through the existing checks. The reply must separate
what was actually saved from what remains unfinished; partial saving does not
mean all work is complete. Shared safety failures, such as a project mismatch or
failure to read saved content back, still require affected work to stop.

harness-mem keeps only current memory. A correction replaces the old item, and
an item that is no longer valid is deleted. It does not keep old knowledge
versions, archived knowledge copies, change history, or undo.

Relevant memory reaches tasks through native context injection where the host
supports it, or through the Agent's MCP search. Codex and Claude Code can query
on prompt submission; Hermes has a pre-call event. Antigravity's pre-call Hook
reads the latest user step from that conversation's native transcript and
recalls relevant memory once per user turn; unreadable context retains the
availability/MCP path. Grok retains
SessionStart/Stop and requires Agent MCP search for task-specific recall;
OpenCode's system transform supplies availability, with task queries through
Agent MCP. Native task-aware injection is not implemented across every host.
At each completed reply or task,
the authorized lifecycle Hook attempts complete-source preparation,
verification and an addition, update or explicit no-write decision through the
existing worker. It uses the selected command-line Agent; an unavailable
executor is reported instead of silently using a different one. `hm` is for
inspection, review and correction, not the switch that starts daily learning.

Codex and Antigravity wait about 30 seconds after a completed reply before
starting a background memory round. A new user turn cancels that pending wait;
the next completed reply starts a new window. A round already started may
finish. This uses the existing worker and the current host's CLI.
Unreleased recovery lets a later native wake resume an interrupted round after
checking its original source, cumulative budget and remaining finite slices.
Retained-source checks compare relevant current memories without granting new write targets; condition-bearing additions require an independent final meaning judgment.
Empty extraction also receives an independent complete-source check; report body changes require a separate audit of the original meaning and actual changed ranges.
Unfinished source checks and report cleanup can continue within a failed
round's original remaining budget; its failure record and limits stay in place.
Known exhausted report attempts can close without another model call; their original progress, failures and costs remain.
When a wake reading link exceeds its budget, wake returns a bounded no-content notice; the complete task query still drives retrieval.
Recall shows a short notice: Codex uses a native conversation message;
Antigravity asks the current Agent to include it in its first reply through
temporary context, so display there depends on the Agent following that request.
Antigravity App, CLI and IDE transcript directories are supported. Equivalent
Codex project registrations are removed when user-level Hooks cover them.

Antigravity can also run background decisions through its native `agy` CLI:
set `distill.autonomous.cli` to `antigravity`. It uses complete stdin input and
structured output within the existing verification and persistence flow.

## What stays out of the way

The unreleased working tree adds read-only session inventory, complete source
paging and an Agent-proposed theme overview checked against source coverage.
The Agent derives the caller's workspace from its native task context, not the
MCP Router's working directory. For automatic discovery, `inspect_sessions {}`
first returns a metadata-only project summary and session counts across Claude
Code, Codex, Cursor, Grok, Hermes, OpenCode and Antigravity native adapters.
The Agent uses returned source information internally to inspect the requested
scope; users need not supply directories or IDs. Project profiles are optional
context labels, not an authority over names or directories. Old directories in
transcript records never reserve a project name or force a rename. Two roots
with the same basename may use the same label; their selected sessions and
frozen batches remain separate for file and source validation. Users do not
manage directory moves, retirement or name reservations. Discovery neither
imports old sessions nor enables background processing.

The automatic worker retains complete sources and resumable jobs. Explicitly
requested historical organization uses frozen manual batches, readable progress,
pause and continuation through the same source verification and commit owners.
Ordinary daily use requires no manual selection. Current-Agent review does not
require background execution to be enabled.

When the native session is already known, the Agent prepares it directly without
printing a whole-device inventory. Explicit non-writing decisions can close
after complete source/reference checks without declaring their prose verified;
knowledge writes still require the normal evidence gate.

Authorized background Codex decisions use a call-local JSON task profile without
interactive skill catalogs or project instructions. Installed skills and the
human review surface remain available; complete source reading and verification still
precede current-memory writes. See [background execution](docs/background-memory.md).

The automatic-project probe exercises the actual MCP dispatcher, native formats,
SQLite, Notes and ordinary search with deterministic Agent decisions. The
earlier recorded revision passed 772 focused tests and five isolated outcome checks;
live MCP inventory, ordinary search and wake were checked separately. Fixture
results do not prove seven live apps, models or Hooks, or validate the new
user-level lifecycle changes. The global host entry was not synchronized in
that earlier run because user directories were out of scope.
See [MCP setup](docs/mcp-setup.md#session-inspection-and-manual-batches-unreleased)
for the inspection, preparation and retry contract. These additions are not
included in the published `0.9.28` artifacts.

The terminal CLI is for setup, diagnosis, integration repair, and explicit
maintenance. `hm` is the inspection and review entry; ordinary conversations
feed the configured automatic path. When something is wrong or an operator needs
the full diagnosis, use `harness-mem doctor`; detailed statistics, versions,
queues, and repair evidence do not belong in the daily reply. The underlying
MCP tools, session hooks, background organization, SQLite store, source checks,
and diagnostics remain available, but are not steps you need to learn to
remember or retrieve work.

The current development tree exposes 20 MCP tools: the previous 19 plus
`inspect_sessions`. Automatic Dream scheduling remains internal to Hooks
and maintenance, not a public MCP tool. Automatic retrieval returns each memory
once; source checks, recovery tools, and retrieval feedback remain available.
Existing SQLite `project_name` fields remain for compatibility; this change
does not migrate or reclassify real memory. Source access still requires
permission and complete validation within the selected scope, even though
default memory recall spans projects.

Project memory is local by default. Evidence is checked before durable knowledge
is changed, and uncertain or unsafe source cleanup remains opt-in. Read the
[background-memory policy](docs/background-memory.md) before enabling automated
processing in a sensitive project; read the [privacy and cleanup details](docs/quickstart.md#advanced-and-repair) before any destructive maintenance.

## More detail when you need it

- [Quickstart](docs/quickstart.md) — setup, native-host notes, and recovery.
- [MCP setup](docs/mcp-setup.md) — manual or nonstandard Agent connection.
- [Cold-start demo](docs/demo-cold-start.md) — reproducible retrieval demo.
- [IDE hook adapter matrix](docs/ide-hook-adapter-matrix.md) — supported-host capability and installation evidence.
- [Memory adoption contract](docs/memory-adoption.md) — extraction, verification, assimilation, and retrieval design.
- [Roadmap](docs/roadmap.md) and [Changelog](CHANGELOG.md) — release and planned work.

## Contributors

Runtime code lives in `harness_mem/`; `code/plugins/harness-mem/` contains Agent
integration assets; `code/tools/hm-distill/SKILL.md` is an instruction-only
playbook, not a second runtime.

Run the relevant checks before contributing:

```bash
python -m compileall harness_mem
python -m ruff check harness_mem code/plugins code/tools
python -m mypy harness_mem
python -m pytest -q -m "not release_gate"
python -m pytest -q
python -m harness_mem.cli --help
cargo test --workspace
```

For user-visible runtime validation, run:

```bash
python code/tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

Current source package version: **0.9.28**. See GitHub for the
[latest public Release](https://github.com/manhua-man/harness-mem/releases/latest).
