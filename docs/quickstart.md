# Quickstart

This is the shortest path to try `harness-mem` in a local Agent workflow.

## Install

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.3 \
  harness-mem==0.9.3
```

The package is distributed through GitHub Releases rather than PyPI. Pip uses
the release asset index above to select the compatible native wheel.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.3 \
  "harness-mem[hybrid]==0.9.3"
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
deletion does not start; partial failures return non-zero and retain planned,
actual, and post-delete verification counts without copying private content.
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
| Hooks | Inject wake context and stage transcript evidence for Agent-led distillation. |

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
counts, stuck-reason actions, or the conservative Agent-throughput drain estimate.
Doctor's recovery plan is read-only and risk-classified; preview and apply are
always separate commands.

## Daily Loop

Use the matching host-native command. Plain language remains an optional fallback:

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
captures an immutable transcript revision and queues every ordered chunk. The
next Agent-capable wake offers an active lane of at most two jobs. Refills use
three recent jobs followed by one oldest eligible job, with exponential failure
backoff and a daily new-job budget; older evidence stays parked without deletion.
Each offered job is claimed through
`prepare_session_distill(distill_job_id=...)`, so the Agent processes the exact
bounded IDs selected by the drainer instead of reselecting by timestamp.
Without an Agent, status is `waiting_for_agent`, not background processing;
the user does not need to keep invoking `/hm:distill`. That command remains an
explicit immediate/deep-audit entry. In the daily semantic fast path, runtime hash-verifies and checkpoints
each chunk while the Agent reads a ≤3k-token indexed exchange manifest. It then
selects complete semantic windows by exchange index; candidate-grade claims
drill into raw proof only after that selection. Explicit
raw mode retains the full per-chunk lease loop. The Agent then performs an
end-of-session review covering the final request, outcome, contradictions,
unfinished work, and evidence status. Only review-ready jobs may create
idempotent `govern_memory(action="suggest")` candidates.
`finalize_session_distill` applies auto-review and then Dream. Merely preparing
or partially reading a packet is never reported as a completed summary.

During an Agent run, supported clients should send context/tool/save-point
events to `autopilot_search_tick`. The scheduler calls `search_memory` only
when the event contains a concrete memory-backed uncertainty such as a prior
decision question, convention uncertainty, conflict, tool failure, durable
claim grounding, or long-horizon task switch. Manual `/hm:search` is the
fallback when the client cannot expose those events. `autopilot_search_tick`
never replaces `wake`, and `prepare_session_distill` never pretends to synthesize
truth by itself; it preserves complete resumable raw evidence while offering a
smaller semantic consumption view for the candidate/review loop.
