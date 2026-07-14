# Quickstart

This is the shortest path to try `harness-mem` in a local Agent workflow.

## Install

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.8.23.4 \
  harness-mem==0.8.23.4
```

The package is distributed through GitHub Releases rather than PyPI. Pip uses
the release asset index above to select the compatible native wheel.

Optional local vector / hybrid search dependencies:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.8.23.4 \
  "harness-mem[hybrid]==0.8.23.4"
```

Check the CLI:

```bash
harness-mem --help
```

The CLI is for operator setup, doctor checks, integration sync, and explicit
maintenance. Daily memory work should happen through MCP or `/hm:*` commands.
Maintenance import and purge operations are available as
`harness-mem maintenance import` and `harness-mem maintenance purge`; both
preview by default until `--apply` is passed.
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
| Plain language | Ask the Agent to wake, search, distill, or review. |
| `/hm:*` commands | Run the daily workflow from Claude Code. |
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

That install syncs the Daily `/hm:*` commands by default, including dream.
For a project-scoped MCP entry, configure its `cwd` as the workspace and set
`HARNESS_MEM_CLIENT` to the host name. The first MCP initialization then adopts
the project and installs the matching hook suite without replacing existing
hooks. OpenCode uses its project plugin; Antigravity uses `.agents/hooks.json`
with `PreInvocation` and `Stop` JSON bridges. The generic hook-suite installer
remains available for operator repair.
For the current host support matrix and where each host expects hooks to live,
see [IDE hook adapter matrix](ide-hook-adapter-matrix.md).
Session-start wake shows a compact recent-context index first, including recent
transcript requests, source host, estimated read cost, and drilldown IDs. Stable
truth and active handoffs are appended when available; an un-distilled project
is no longer rendered as three empty sections.
`get_project_status` and CLI status also expose one compact integration line for
the current project, host, hooks, transcript observations, and distill queue.

## Daily Loop

Ask your Agent to use `harness-mem` in plain language:

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

Dream is the final stage of the audited maintenance pipeline. A Stop hook only
syncs transcript evidence and queues a distill task. The next Agent-capable
wake consumes that task through the same `/hm:distill` flow: evidence packet,
Agent judgment, `suggest_*` candidates, `auto_review_candidates(apply=true)`,
then Dream. Preparing a packet is never reported as a completed summary.
Counts and candidate IDs stay on the audit surface.

During an Agent run, supported clients should send context/tool/save-point
events to `autopilot_search_tick`. The scheduler calls `search_memory` only
when the event contains a concrete memory-backed uncertainty such as a prior
decision question, convention uncertainty, conflict, tool failure, durable
claim grounding, or long-horizon task switch. Manual `/hm:search` is the
fallback when the client cannot expose those events. `autopilot_search_tick`
never replaces `wake`, and `prepare_session_distill` never pretends to synthesize
truth by itself; it only packages evidence for the candidate/review loop.
