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

Automatic recording supports seven clients. When the user requests it, setup
installs the matching Hook adapter for the workspace. Ordinary recall and
manual session organization do not require Hook installation:

| Client flag | Generated files | Runtime action mapping | ID source |
|---|---|---|---|
| `cursor` | `.cursor/hooks.json` plus `.cursor/hooks/session-start.sh`, `.cursor/hooks/after-agent.sh` | `sessionStart` -> `wake-start`; `stop` -> maintenance | stdin `conversation_id` / `session_id` |
| `claude-code` | `.claude/settings.json` plus `.claude/hooks/session-start.sh`, `.claude/hooks/after-turn.sh` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | stdin `session_id` |
| `grok` | `.grok/hooks/harness-mem.json` | `SessionStart` -> `wake-start`; `Stop` -> maintenance | native stdin `sessionId`, legacy `session_id` / `conversation_id`, or `GROK_SESSION_ID`; no static per-host session label |
| `codex` | `.codex/hooks.json` | `SessionStart` -> `wake-start`; `Stop` -> maintenance; one-time native Hook trust required | `harness-mem-hook --adapter codex-stop` reads hook stdin JSON |
| `hermes` | `<active Hermes profile>/config.yaml` (resolution below) | `pre_llm_call` -> `wake-start`; `post_llm_call` -> maintenance | `harness-mem-hook` Hermes adapters read hook stdin JSON |
| `opencode` | `.opencode/plugins/harness-mem.ts` | `session.created` -> `wake-start`; `session.idle` -> maintenance | `properties.info.id` / `properties.sessionID` |
| `antigravity` | `.agents/hooks.json` | `PreInvocation` -> wake injection; `Stop` -> evidence staging | `harness-mem-hook` adapters read camelCase hook stdin JSON |

Live-host exercise (2026-10-15, unreleased): native application execution and
adapter code validation are separate results. Codex created a real conversation,
organized it through MCP, recalled it in another native session, and replaced
eleven days with twelve days. A new native CLI invocation completed the original
correction job by replaying its exact committed Review plan through all runtime
checks; fresh MCP/SQLite/Note readback agreed. Details are in `docs/roadmap.md`;
successful storage alone was not counted as successful session completion.
Antigravity read the dedicated MCP store in a real model session, then its
organizing attempt exposed a native-log classification defect. Native
`GENERIC` records are now recognized without treating metadata
alone as conversation content; a new stdio process reopened the original failed
source and prepared the same frozen batch without changing the source file.
Its model retry hit account quota, so full native organization remains unverified.
Claude connected MCP and ran SessionStart but its configured model routes failed.
Grok was not signed in; its workspace also lacked native Hook trust, so an empty
native Hook list was not evidence of a registration defect. Hermes reached
session startup but timed out without a completed answer. OpenCode's task-local
official executable launched, but provider model discovery returned HTTP 401;
chat inference was not attempted. Cursor GUI interaction was stopped by the
operator before a model request. Per operator scope, unavailable native runs are
not mandatory after adapter checks. None of these partial/untested rows is a
seven-host natural-Hook acceptance claim. Raw case evidence is retained under
`.tmp/seven-host-live-20261015/`. The temporary Antigravity test-MCP permission
was removed and its original settings restored byte-for-byte.

Unreleased repair (2026-10-14): Claude Code and Cursor now register the scripts
with their native event configuration, rather than reporting success for two
unregistered shell files. Their JSON merge retains unrelated settings/events;
malformed JSON and conflicting managed entries stop before scripts are written.
Changed generated files still require explicit review and `--force`. A forced
Claude update retains unrelated commands even inside a mixed Hook group.
These two hosts require Bash for the installed shell wrappers. Their Stop
wrappers preserve the runner's failing exit status; missing native identity
does not dispatch maintenance. Cursor startup returns `additional_context`.

The declarations follow [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
and [Cursor Hooks](https://cursor.com/docs/hooks). OpenCode uses its
[plugin events](https://opencode.ai/docs/plugins/) and
[SDK prompt body](https://opencode.ai/docs/sdk/#tui), not a bare text argument.
Node replays the generated plugin with fictional native events and a stub
shell/SDK, while Git Bash exercises generated Stop wrappers with a fake runner.
These checks do not prove live application discovery, approvals, natural events
or real model execution. Grok's stdin identity is covered by a contract fixture,
not a new live Grok run. Antigravity failure output no longer says staging
finished when the runtime failed. Codex and Antigravity keep their explicitly
bound project root even if a payload names another workspace. Global Hermes
still resolves the workspace dynamically. Hermes config merging rejects
unsupported event indentation before writes rather than corrupting valid YAML;
arbitrary indentation support remains open.

Daily command discovery is a separate, user-level install. Quickstart installs
one entry for the current Agent app, so a fresh unrelated project can invoke it
before it has any project-local files. An operator may explicitly sync more
apps, but that is not the normal setup path:

| Host | User-level command discovery | Invocation |
|---|---|---|
| Claude Code | `~/.claude/commands/hm.md` | `/hm` |
| Codex | `~/.codex/skills/hm/SKILL.md` | `$hm` |
| Cursor | `~/.cursor/skills/hm/SKILL.md` | `/hm` |
| Grok | `~/.grok/skills/hm/SKILL.md` | `/hm` |
| Hermes | `<active Hermes profile>/skills/hm/SKILL.md` | `/hm` |
| OpenCode | `~/.config/opencode/commands/hm.md` | `/hm` |
| Antigravity | `~/.gemini/antigravity/global_workflows/hm.md` | `/hm` |

The entry contains no project path. Requested automatic recording prepares
only the intended workspace and its native Hook adapter. Ordinary `hm` recall,
manual organization and MCP initialization do not adopt a project or write
Hook files. Codex still requires its native trust approval for each new or
changed project Hook manifest.

Hermes command discovery and Hook installation share the existing active-profile
rules: a nonempty `HERMES_HOME` wins; otherwise Windows uses
`%LOCALAPPDATA%/hermes`, or `~/AppData/Local/hermes` if that variable is absent;
macOS/Linux uses `~/.hermes`. Use the same profile environment for Quickstart
and Hook sync. No other profile is changed. The installer API's explicit
`home_dir` compatibility argument still targets `home_dir/.hermes/config.yaml`;
it is not a new CLI setting.

The checked-in templates live in `harness_mem/integration/templates/` and are
wired by `_suite_specs()` in `harness_mem/integration/repair.py`, with the
Hermes config merge owned by `harness_mem/integration/installer.py`.

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
or summarize a transcript. A post-turn Hook resolves the current host,
synchronizes the native transcript evidence, creates or advances its session
job, and emits a source-bound Dream activity signal. The CLI `wake-up` command
retains a separate best-effort sync option for non-hook environments.

Wake remains synchronous because the host needs its returned context before the
session or invocation proceeds. Post-turn handling is receipt-first and
generation-safe: another event can replace a pending activity signal without
creating concurrent writers or dropping the final turn. The Hook does not call a
provider or mutate knowledge. Authorized Dream later performs the unattended
session and project-governance work; explicit `distill` remains in the active
host.

Hermes `pre_llm_call` and Antigravity `PreInvocation` may fire repeatedly inside
one conversation. When their native payload includes a stable `session_id` or
`conversationId`, harness-mem reuses the successful wake receipt and emits no
duplicate context. Fallback trigger labels are deliberately not deduplicated
because they cannot prove two invocations belong to the same session.
Session-start injection uses a compact recent-context index. The index is
derived from project-scoped transcript Observations; it does not replace the
immutable transcript ledger or governed truth layer, and recent work does not
need a manual “remember this session” request before it becomes visible.

## Transcript adapter contract

### Automatic discovery (unreleased)

The Agent derives the caller workspace from native task context, not the MCP
Router's working directory. `inspect_sessions {}` first returns a metadata-only
project summary with counts. The Agent uses returned bindings internally for
narrowed inventory and selected-source paging; users do not supply directories
or IDs. Different roots remain isolated even when project names match.

| Native adapter | Formats exercised by the isolated automatic-project probe |
|---|---|
| Claude Code | Project-bucket conversation JSONL |
| Codex | Rollout JSONL in current and archived session directories |
| Cursor | Exported JSONL; native SQLite composer/bubble records with workspace metadata |
| Grok | Project-bucket `chat_history.jsonl` |
| Hermes | `session_*.json`; archived sessions/messages in `state.db` |
| OpenCode | SQLite `session`/`message`/`part` records |
| Antigravity | Brain transcript JSONL; CLI history with conversation transcripts |

Inventory does not import, create jobs, write memory or start background work.
Metadata references are not verified source revisions. Before freezing a manual
batch, preparation independently reads and revalidates each selected full source
and its ownership. Resume derives project/root from the frozen batch; newly
discovered sessions stay outside it. Manual batches retain sources.

`harness_mem/qualification/automatic_projects_outcome_probe.py` exercises two
isolated variants (`files` and `containers_and_archives`) through the actual MCP
dispatcher, native adapters, verification gates, SQLite, Note digest readback and
ordinary search after reopening storage. Agent semantic decisions and filesystem
locations are deterministic fixtures. This does not validate seven live apps,
models or Hooks, every native schema, or an older installed MCP server. These
working-tree additions are absent from published `0.9.28` artifacts.

Every shipped transcript adapter implements the same evidence boundary:

1. `list_sessions` discovers native host sessions and continues scanning past
   unchanged recent files so an older backlog can still advance.
2. `sync_session` reads one complete native source and records a new immutable
   revision whenever its permitted transcript changes. SQLite-backed OpenCode
   uses a deterministic complete export. Codex rollouts are host event logs, so
   their revisions contain only the normalized user/assistant conversation;
   the native-file hash remains available only for safe cleanup comparison.
3. The revision is split into complete ordered chunks. Concatenating those
   chunks reconstructs the normalized transcript without character loss.
4. `session_to_observation` produces only a derived search rendering. It may be
   rebuilt and must never be treated as the lossless source of truth.
5. The revision queues a resumable distill job. A Hook stops after sync and
   wakes Dream with the exact session/revision reference. Dream is the
   unattended executor: it reads the triggering session, performs the required
   extraction, verification, and assimilation, then performs project-level
   governance. An explicitly invoked `distill` instead stays in the active host.

`limit` is an optional caller-selected changed-session count, not a newest-file
window or a daily quota. When it is omitted, the adapter processes every
matching changed session in the project scope. A persistent frontier still
alternates the recent and historical lanes when a caller chooses a small count;
failed sources use a backoff retry lane so they cannot block history. A source
absent from a complete host inventory becomes `missing`, while all captured
revisions remain locally readable.

For Codex Desktop, a host-authored delegation envelope can contain capabilities,
project instructions, and the user's request in one event. The adapter retains
only the explicit request payload. A repeated Stop notification for an already
completed matching job only restores its terminal receipt and, if needed, its
Note; it never invokes the semantic provider again. If that matching job is
still in a scheduled retry window, a repeated Stop produces an explicit
`deferred` receipt with its retry time; it neither restages the transcript nor
misreports the state as an evidence-ingest failure.

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

The automatic `get_project_status(project_root, host_client)` call reports only
whether the project is usable or preparation failed; it does not expose the
Hook receipt, artifact fingerprint, version, queue, or repair detail. Doctor
checks successful generated-Hook execution against the current artifact
fingerprint. Codex project command hooks require review in **Settings > Hooks**
before Codex runs them. A present manifest without a matching successful
`SessionStart` receipt still requires review; changing the manifest invalidates
the receipt.

The installer validates `harness-mem-hook --version` before writing Hook
artifacts, so IDE hooks do not depend on a bare `python` selected from the
IDE's `PATH`. For Cursor and Claude Code shell hooks, set
`HARNESS_MEM_HOOK_DEBUG=1` before launching the IDE to surface a fail-open
Hook action failure.

### Upgrade conflicts and explicit recovery

For generated project Hook files, matching content is `unchanged` (shell
generation timestamps are informational). A changed runner, package header,
template, project binding or user edit is a conflict by default; legacy Python
Hooks are also preserved. Hermes reports a conflict when an existing marked
managed section differs from the expected runner or adapter declaration.
Hook sync returns a failure with `error_kind: conflict`; it does not silently
replace the conflicting content.

Use `harness-mem doctor` and
`harness-mem integration hooks sync --client <host> --project-root .` to locate
the problem. Check ownership, the project binding and the installed differences
against the packaged template and verified runner before explicitly adding
`--force` for that host. Hermes users must verify the active profile and the
config path reported by sync: Doctor's existing global artifact inventory still
uses `~/.hermes/config.yaml`, so it may not inspect a custom or Windows default
profile. The installer fix does not extend that diagnostic inventory.

Force replaces generated project files, including any user modifications.
For Hermes it replaces marked managed sections, retaining unrelated YAML and
Hook entries; inline content that cannot be safely merged or incomplete markers
still fail without writing. Keep needed custom content before authorizing an
overwrite. Antigravity retains its separate existing manifest merge behavior;
changed managed entries require force, and unrelated entries remain.

After a reviewed update, repeat sync without force and rerun Doctor. An
`unchanged` result proves the installed content matches; a live Hook receipt is
still needed to prove execution. Review changed Codex Hooks in **Settings >
Hooks**. See [Quickstart conflict recovery](quickstart.md#recover-a-hook-upgrade-conflict)
for the command sequence. None of these commands automatically changes MCP
connections or enables unattended memory processing.

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
| Hermes | Shell hooks in YAML, plugin hooks in Python, gateway hooks in `HOOK.yaml` dirs | Shell hooks live in `<active Hermes profile>/config.yaml`; gateway hooks live under that profile's `hooks/<name>/` | `pre_llm_call`, `post_llm_call` | Installer patches profile-global YAML with `harness-mem-hook` adapters | Shipped; shared command/Hook profile resolution in unreleased tree |
| OpenCode | JS/TS plugin event handlers, not shell hook files | `<project>/.opencode/plugins/`, `~/.config/opencode/plugins/`, or plugin objects in config | `session.created`, `session.idle` | Generate a plugin file such as `.opencode/plugins/harness-mem.ts` | Shipped; SQLite ingest verified |
| Antigravity (`agy`) | Workspace JSON command hooks | `<project>/.agents/hooks.json` | `PreInvocation`, `Stop` | Console adapter JSON stdin/stdout bridge plus JSONL transcript adapter | Shipped |

Verification level:

The unreleased working tree adds Cursor read-only SQLite history inspection
alongside exported JSONL. `code/tests/test_cursor_sqlite_history.py` covers
synthetic `cursorDiskKV` composer/bubble records, `workspace.json` ownership,
project mismatch, corrupt/unknown layouts and consistent snapshots. This is
fixture coverage, not support for every live Cursor database format or proof
of a live Hook run. Unknown ownership remains outside manual selection.

The working-tree `inspect_sessions` inventory, source paging and theme coverage
are read-only. Manual fixed batches run in the current Agent independently of
the background CLI and retain sources. These additions are not part of the
published 0.9.28 artifacts.

The following local-runtime observations are historical, not acceptance of
current changes. On 2026-09-24 the selected Hermes CLI preflight failed with
HTTP 400 for missing `x-opencode-session`; the complete background Hook did not
start. That blocker remains separate from deterministic manual-flow fixtures.

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
- Antigravity's one daily entry is a user-global workflow, not a project-local
  `.agents/skills` copy.
- `Hermes` transcript ingest accepts verified `session_*.json` exports and the
  upstream `sessions/messages` SQLite schema from `state.db`.

## Design rule

When adding a new host:

1. Freeze the native hook location and event names.
2. Freeze how we get a stable trigger/session/turn identifier.
3. Check in the adapter template.
4. Make the installer render the concrete instance.
5. Do not rely on the runtime agent to synthesize host glue ad hoc.
