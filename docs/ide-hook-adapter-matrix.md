# IDE Hook Adapter Matrix

`harness-mem` does not ask the live agent to invent hook files on demand.
The repo must carry host-specific adapter templates up front, and the installer
renders concrete files or config into the user's project or home directory.

That split is intentional:

- every host uses a different hook declaration format
- hook files do not live in the same place
- event names differ
- some hosts pass IDs through env vars, others through stdin JSON
- some hosts are project-local, others are user-global
- some hosts use shell hooks, others use JSON manifests or JS/TS plugins

The agent can decide *which* adapter to install. It should not be expected to
invent the adapter schema at runtime.

## Current `harness-mem` support

Today the MCP bootstrap supports seven clients and installs their hook adapters
automatically:

| Client flag | Generated files | Runtime action mapping | ID source |
|---|---|---|---|
| `cursor` | `.cursor/hooks/session-start.sh`, `.cursor/hooks/after-agent.sh` | `wake-start`, `post-turn-maintenance` | `CURSOR_TURN_ID` |
| `claude-code` | `.claude/hooks/session-start.sh`, `.claude/hooks/after-turn.sh` | `wake-start`, `post-turn-maintenance` | `CLAUDE_CODE_TURN_ID` |
| `grok` | `.grok/hooks/harness-mem.json` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | static trigger ids in manifest |
| `codex` | `.codex/hooks.json` | `SessionStart` -> `wake-start`; `Stop` -> maintenance; one-time native Hook trust required | `harness-mem-hook --adapter codex-stop` reads hook stdin JSON |
| `hermes` | `~/.hermes/config.yaml` | `pre_llm_call` -> `wake-start`; `post_llm_call` -> maintenance | `harness-mem-hook` Hermes adapters read hook stdin JSON |
| `opencode` | `.opencode/plugins/harness-mem.ts` | `session.created` -> `wake-start`; `session.idle` -> maintenance | plugin event payload |
| `antigravity` | `.agents/hooks.json` | `PreInvocation` -> wake injection; `Stop` -> evidence staging | `harness-mem-hook` adapters read camelCase hook stdin JSON |

The checked-in templates live in `harness_mem/integration/templates/` and are
wired by `_suite_specs()` plus the Hermes config installer in
`harness_mem/commands/integration_cmds.py`.

Native transcript capture is now adapter-backed for Claude Code, Cursor, Codex,
Grok, Hermes, OpenCode, and Antigravity. OpenCode is read from its verified
SQLite `session`/`message`/`part` database. Antigravity is read from the
verified `.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`
layout and matched by workspace paths recorded in tool arguments.

Antigravity lifecycle hooks use its verified workspace customization surface:
`.agents/hooks.json`. Commands receive camelCase JSON on stdin and return JSON
on stdout. The installer merges managed `PreInvocation` and `Stop` entries
without removing unrelated project hooks.

`wake-start` injects already-captured context and pending work; it does not read
or summarize a transcript. Hook-triggered post-turn/idle maintenance resolves
the current host, synchronizes native transcript evidence, and queues lossless
distill work. The CLI `wake-up` command retains a separate best-effort sync
option for non-hook environments.
Session-start injection uses a compact recent-context index. The index is
derived from project-scoped transcript Observations; it does not replace the
immutable transcript ledger or governed truth layer, and it does not require
`/hm:distill` before recent work is visible.

## Transcript adapter contract

Every shipped transcript adapter implements the same evidence boundary:

1. `list_sessions` discovers native host sessions and continues scanning past
   unchanged recent files so an older backlog can still advance.
2. `sync_session` reads one complete native source, captures exact bytes (or a
   deterministic complete export for SQLite-backed OpenCode), and records a new
   immutable revision whenever that source grows or changes.
3. The revision is split into complete ordered chunks. Concatenating those
   chunks reconstructs the normalized transcript without character loss.
4. `session_to_observation` produces only a derived search rendering. It may be
   rebuilt and must never be treated as the lossless source of truth.
5. The revision queues a resumable distill job. Hooks stop after sync and queue;
   an Agent processes all chunks, checkpoints each result, performs the required
   final-session review, creates idempotent candidates, and calls
   `finalize_session_distill` to run auto-review and Dream.

`limit` is a changed-session budget, not a newest-file window. A persistent
frontier alternates the recent and historical lanes when the budget is one;
failed sources use a backoff retry lane so they cannot block history. A source
absent from a complete host inventory becomes `missing`, while all captured
revisions remain locally readable.

Support is claimed only when a native location, a real format, and regression
fixtures exist for that host. A hook adapter and a transcript adapter are
separate capabilities; shipping one never implies the other.

## Runtime diagnostics

Run `harness-mem doctor` from the project root to inspect hook runtime state.
The `Hook runtime` block reports:

- the absolute `harness-mem-hook` executable bound into generated Hook files
- its verified package version, or a concise executable failure
- which generated hook artifacts are installed, legacy, or not bound
- whether installed hook files still contain the current project root

`get_project_status` additionally tracks successful generated-Hook execution
against the current artifact fingerprint. Codex project command hooks require
review in **Settings > Hooks** before Codex runs them. A present manifest with
no matching successful `SessionStart` receipt is reported as
`review_required`, not `ok`; changing the manifest invalidates the receipt.

The installer validates `harness-mem-hook --version` before writing Hook
artifacts, so IDE hooks do not depend on a bare `python` selected from the
IDE's `PATH`. For Cursor and Claude Code shell hooks, set
`HARNESS_MEM_HOOK_DEBUG=1` before launching the IDE to surface a fail-open
Hook action failure.

Run `harness-mem integration transcript-evidence` to inspect local transcript
evidence separately from hook-install support. Grok's project-scoped
`chat_history.jsonl` layout and Hermes' JSON sessions plus `sessions/messages`
`state.db` layouts are adapter-backed when present. OpenCode evidence validates
the SQLite schema, while Antigravity evidence validates both brain transcripts
and project-scoped `antigravity-cli/history.jsonl`. Evidence status is
local-machine state; adapter availability is installed-code state.

## Host matrix

| Host | Native hook surface | Where hooks live | Good `harness-mem` event mapping | Adapter shape we would need | Status |
|---|---|---|---|---|---|
| Cursor | Shell hook files | `<project>/.cursor/hooks/*.sh` | `session-start` -> `wake-start`; `after-agent` -> maintenance | Checked-in shell templates | Shipped |
| Claude Code | Shell hook files | `<project>/.claude/hooks/*.sh` | `session-start` -> `wake-start`; `after-turn` -> maintenance | Checked-in shell templates | Shipped |
| Grok | JSON hook manifests plus plugin hooks | `<project>/.grok/hooks/*.json`, `~/.grok/hooks/*.json`, plugin `hooks/hooks.json` | `SessionStart`, `Stop` | Generate a `.grok/hooks/harness-mem.json` manifest | Shipped |
| Codex | `hooks.json`, inline config, or plugin hooks | `<project>/.codex/hooks.json`, `~/.codex/hooks.json`, or inline `.codex/config.toml`; plugins can ship `hooks/hooks.json` | `SessionStart`, `Stop` | Generate `.codex/hooks.json` bound to `harness-mem-hook` | Shipped; user must trust new/changed command hooks once in Codex Settings |
| Hermes | Shell hooks in YAML, plugin hooks in Python, gateway hooks in `HOOK.yaml` dirs | Shell hooks live in `~/.hermes/config.yaml`; gateway hooks live under `~/.hermes/hooks/<name>/` | `pre_llm_call`, `post_llm_call` | Installer patches user-global YAML with `harness-mem-hook` adapters | Shipped |
| OpenCode | JS/TS plugin event handlers, not shell hook files | `<project>/.opencode/plugins/`, `~/.config/opencode/plugins/`, or plugin objects in config | `session.created`, `session.idle` | Generate a plugin file such as `.opencode/plugins/harness-mem.ts` | Shipped; SQLite ingest verified |
| Antigravity (`agy`) | Workspace JSON command hooks | `<project>/.agents/hooks.json` | `PreInvocation`, `Stop` | Console adapter JSON stdin/stdout bridge plus JSONL transcript adapter | Shipped |

Verification level:

- Repository fixtures + project-isolation negative tests: Cursor, Claude Code,
  Grok, Codex, Hermes, OpenCode, Antigravity.
- Local runtime evidence on this machine: Cursor, Claude Code, Grok, Codex CLI,
  Hermes, Antigravity.
- OpenCode uses a verified `session`/`message`/`part` SQLite fixture and adapter
  contract test; a live OpenCode installation is not claimed on this machine.

## What this means for installer design

There is no single "universal hook file" we can stamp everywhere.

We need one adapter per host family:

1. Shell-file adapters
   - Cursor
   - Claude Code

2. JSON-manifest adapters
   - Grok
   - Codex

3. Global-config adapters
   - Hermes

4. Plugin-code adapters
   - OpenCode

5. JSON stdin/stdout adapters
   - Antigravity

That is why the repo should carry templates ahead of time and the installer
should only fill in project root, command path, and small host-specific IDs.

## Practical guidance

- `Hermes` is deliberately different UX because the declaration is user-global
  config, not a repo-local hook file.
- `OpenCode` remains a plugin adapter, not a shell-hook adapter.
- `Antigravity` uses project-local `.agents/hooks.json`; its transcript adapter
  reads verified brain `transcript[_full].jsonl` and CLI `history.jsonl` formats.
- `Hermes` transcript ingest accepts verified `session_*.json` exports and the
  upstream `sessions/messages` SQLite schema from `state.db`.

## Design rule

When adding a new host:

1. Freeze the native hook location and event names.
2. Freeze how we get a stable trigger/session/turn identifier.
3. Check in the adapter template.
4. Make the installer render the concrete instance.
5. Do not rely on the runtime agent to synthesize host glue ad hoc.
