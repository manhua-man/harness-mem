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
| `codex` | `.codex/hooks.json`, `.codex/hooks/harness_mem_stop.py` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | wrapper reads hook stdin JSON |
| `hermes` | `~/.hermes/config.yaml`, `~/.hermes/agent-hooks/harness_mem_*.py` | `pre_llm_call` -> `wake-start`; `post_llm_call` -> maintenance | wrapper reads hook stdin JSON |
| `opencode` | `.opencode/plugins/harness-mem.ts` | `session.created` -> `wake-start`; `session.idle` -> maintenance | plugin event payload |
| `antigravity` | `.agents/hooks.json`, `.agents/hooks/harness_mem_*.py` | `PreInvocation` -> wake injection; `Stop` -> evidence staging | wrapper reads camelCase hook stdin JSON |

The checked-in templates live in `harness_mem/integration/templates/` and are
wired by `_suite_specs()` plus the Hermes config installer in
`harness_mem/commands/integration_cmds.py`.

Native transcript ingest is now adapter-backed for Claude Code, Cursor, Codex,
Grok, Hermes, OpenCode, and Antigravity. OpenCode is read from its verified
SQLite `session`/`message`/`part` database. Antigravity is read from the
verified `.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`
layout and matched by workspace paths recorded in tool arguments.

Antigravity lifecycle hooks use its verified workspace customization surface:
`.agents/hooks.json`. Commands receive camelCase JSON on stdin and return JSON
on stdout. The installer merges managed `PreInvocation` and `Stop` entries
without removing unrelated project hooks.

The CLI wake auto-sync path uses the project-scoped Cursor, Codex, Grok, Hermes,
OpenCode, and Antigravity adapters. Hook-triggered post-turn maintenance follows the same host
resolution through `/hm:distill`'s lower-level transcript sync step.
Session-start injection uses a compact recent-context index. The index is
derived from project-scoped transcript observations; it does not replace the
governed truth layer or require `/hm:distill` before recent work is visible.

## Runtime diagnostics

Run `harness-mem doctor` from the project root to inspect hook runtime state.
The `Hook runtime` block reports:

- whether the current shell `python` can import `harness_mem`
- the resolved Python executable, Python version, and harness-mem version
- which generated hook artifacts are installed
- whether installed hook files still contain the current project root

This probe uses the current shell environment. IDE hook processes can still see
a different `PATH` or virtual environment. For Cursor and Claude Code shell
hooks, set `HARNESS_MEM_HOOK_DEBUG=1` before launching the IDE to surface
host-entry import/runtime failures that are normally silenced by fail-open
hook behavior.

Run `harness-mem integration transcript-evidence` to inspect local transcript
evidence separately from hook-install support. Grok's project-scoped
`chat_history.jsonl` layout and Hermes' global `~/.hermes/sessions/session_*.json`
layout are adapter-backed when present on the machine. OpenCode evidence
validates the SQLite schema, while Antigravity evidence validates matching
`transcript.jsonl` files. Evidence status is local-machine state; adapter
availability is installed-code state.

## Host matrix

| Host | Native hook surface | Where hooks live | Good `harness-mem` event mapping | Adapter shape we would need | Status |
|---|---|---|---|---|---|
| Cursor | Shell hook files | `<project>/.cursor/hooks/*.sh` | `session-start` -> `wake-start`; `after-agent` -> maintenance | Checked-in shell templates | Shipped |
| Claude Code | Shell hook files | `<project>/.claude/hooks/*.sh` | `session-start` -> `wake-start`; `after-turn` -> maintenance | Checked-in shell templates | Shipped |
| Grok | JSON hook manifests plus plugin hooks | `<project>/.grok/hooks/*.json`, `~/.grok/hooks/*.json`, plugin `hooks/hooks.json` | `SessionStart`, `Stop` | Generate a `.grok/hooks/harness-mem.json` manifest | Shipped |
| Codex | `hooks.json`, inline config, or plugin hooks | `<project>/.codex/hooks.json`, `~/.codex/hooks.json`, or inline `.codex/config.toml`; plugins can ship `hooks/hooks.json` | `SessionStart`, `Stop` | Generate `.codex/hooks.json` plus a Stop wrapper script | Shipped |
| Hermes | Shell hooks in YAML, plugin hooks in Python, gateway hooks in `HOOK.yaml` dirs | Shell hooks live in `~/.hermes/config.yaml` and usually point at `~/.hermes/agent-hooks/`; gateway hooks live under `~/.hermes/hooks/<name>/` | `pre_llm_call`, `post_llm_call` | Installer patches user-global YAML and registers home-local wrapper scripts | Shipped |
| OpenCode | JS/TS plugin event handlers, not shell hook files | `<project>/.opencode/plugins/`, `~/.config/opencode/plugins/`, or plugin objects in config | `session.created`, `session.idle` | Generate a plugin file such as `.opencode/plugins/harness-mem.ts` | Shipped; SQLite ingest verified |
| Antigravity (`agy`) | Workspace JSON command hooks | `<project>/.agents/hooks.json` plus wrapper scripts | `PreInvocation`, `Stop` | JSON stdin/stdout bridge plus JSONL transcript adapter | Shipped |

Verification level:

- Local runtime + local docs: Cursor, Claude Code, Grok, Codex CLI, Hermes, Antigravity
- Upstream docs only on this machine: OpenCode

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
  separately reads the verified brain `transcript.jsonl` format.

## Design rule

When adding a new host:

1. Freeze the native hook location and event names.
2. Freeze how we get a stable trigger/session/turn identifier.
3. Check in the adapter template.
4. Make the installer render the concrete instance.
5. Do not rely on the runtime agent to synthesize host glue ad hoc.
