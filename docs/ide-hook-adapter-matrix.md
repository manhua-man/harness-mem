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

Today `harness-mem integration install-hook-suite` supports six clients:

| Client flag | Generated files | Runtime action mapping | ID source |
|---|---|---|---|
| `cursor` | `.cursor/hooks/session-start.sh`, `.cursor/hooks/after-agent.sh` | `wake-start`, `post-turn-maintenance` | `CURSOR_TURN_ID` |
| `claude-code` | `.claude/hooks/session-start.sh`, `.claude/hooks/after-turn.sh` | `wake-start`, `post-turn-maintenance` | `CLAUDE_CODE_TURN_ID` |
| `grok` | `.grok/hooks/harness-mem.json` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | static trigger ids in manifest |
| `codex` | `.codex/hooks.json`, `.codex/hooks/harness_mem_stop.py` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | wrapper reads hook stdin JSON |
| `hermes` | `~/.hermes/config.yaml`, `~/.hermes/agent-hooks/harness_mem_*.py` | `pre_llm_call` -> `wake-start`; `post_llm_call` -> maintenance | wrapper reads hook stdin JSON |
| `opencode` | `.opencode/plugins/harness-mem.ts` | `session.created` -> `wake-start`; `session.idle` -> maintenance | plugin event payload |

The checked-in templates live in `harness_mem/integration/templates/` and are
wired by `_suite_specs()` plus the Hermes config installer in
`harness_mem/commands/integration_cmds.py`.

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

## Host matrix

| Host | Native hook surface | Where hooks live | Good `harness-mem` event mapping | Adapter shape we would need | Status |
|---|---|---|---|---|---|
| Cursor | Shell hook files | `<project>/.cursor/hooks/*.sh` | `session-start` -> `wake-start`; `after-agent` -> maintenance | Checked-in shell templates | Shipped |
| Claude Code | Shell hook files | `<project>/.claude/hooks/*.sh` | `session-start` -> `wake-start`; `after-turn` -> maintenance | Checked-in shell templates | Shipped |
| Grok | JSON hook manifests plus plugin hooks | `<project>/.grok/hooks/*.json`, `~/.grok/hooks/*.json`, plugin `hooks/hooks.json` | `SessionStart`, `Stop` | Generate a `.grok/hooks/harness-mem.json` manifest | Shipped |
| Codex | `hooks.json`, inline config, or plugin hooks | `<project>/.codex/hooks.json`, `~/.codex/hooks.json`, or inline `.codex/config.toml`; plugins can ship `hooks/hooks.json` | `SessionStart`, `Stop` | Generate `.codex/hooks.json` plus a Stop wrapper script | Shipped |
| Hermes | Shell hooks in YAML, plugin hooks in Python, gateway hooks in `HOOK.yaml` dirs | Shell hooks live in `~/.hermes/config.yaml` and usually point at `~/.hermes/agent-hooks/`; gateway hooks live under `~/.hermes/hooks/<name>/` | `pre_llm_call`, `post_llm_call` | Installer patches user-global YAML and registers home-local wrapper scripts | Shipped |
| OpenCode | JS/TS plugin event handlers, not shell hook files | `<project>/.opencode/plugins/`, `~/.config/opencode/plugins/`, or plugin objects in config | `session.created`, `session.idle` | Generate a plugin file such as `.opencode/plugins/harness-mem.ts` | Shipped |
| Antigravity (`agy`) | Lifecycle hook surface exists, but local offline docs are incomplete | Local CLI confirms `/hooks`; settings live in `~/.gemini/antigravity-cli/settings.json`; shipped offline refs do not yet spell out the hook declaration schema/path | Unknown until the native schema is confirmed | Do not implement blind; fetch the official hooks doc first and then freeze a real adapter | Needs live-doc confirmation |

Verification level:

- Local runtime + local docs: Cursor, Claude Code, Grok, Codex CLI, Hermes, Antigravity partial
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

5. Not-yet-frozen adapters
   - Antigravity

That is why the repo should carry templates ahead of time and the installer
should only fill in project root, command path, and small host-specific IDs.

## Practical guidance

- `Hermes` is deliberately different UX because the declaration is user-global
  config, not a repo-local hook file.
- `OpenCode` remains a plugin adapter, not a shell-hook adapter.
- `Antigravity` stays in "research" until the official hook schema is captured
  from the live docs.

## Design rule

When adding a new host:

1. Freeze the native hook location and event names.
2. Freeze how we get a stable trigger/session/turn identifier.
3. Check in the adapter template.
4. Make the installer render the concrete instance.
5. Do not rely on the runtime agent to synthesize host glue ad hoc.
