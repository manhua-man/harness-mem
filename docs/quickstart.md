# Quickstart

Install `harness-mem`, run Quickstart once for the Agent app you use, and
authorize its background processing. Then converse normally;
`hm` is available for memory inspection and human review.

The user-level lifecycle setup below is unreleased development-tree behavior;
published `0.9.28` does not include this new Quickstart flow.

## Install once

Install the release with this single-line command in PowerShell, Command Prompt, or Bash:

```text
python -m pip install --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.28 harness-mem==0.9.28
```

The package is distributed through GitHub Releases rather than PyPI. Optional
local vector or hybrid search dependencies use the same index:

```text
python -m pip install --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.28 "harness-mem[hybrid]==0.9.28"
```

Run Quickstart once for each Agent app you actually use, not once per project.
The current directory does not matter:

```bash
harness-mem quickstart --confirm
```

Quickstart identifies Codex and Claude Code directly. If it cannot identify the
current app, it stops instead of guessing. Supply the app name once:

```bash
harness-mem quickstart --client cursor --confirm
```

Quickstart installs the app's entry (`$hm` in Codex, `/hm` elsewhere) and
user-level lifecycle Hooks. `--confirm` authorizes background model processing
once; omitting it leaves authorization unchanged. The current source supports
this setup for Claude Code, Codex, Cursor, Grok, Hermes, OpenCode and Antigravity.
Hooks derive each task's workspace dynamically, without per-project setup.
Quickstart neither imports historical sessions nor inspects or changes MCP
settings. Source support does not establish live acceptance of all seven hosts.

For Hermes, run Quickstart and later Hook repair with the same active
profile: `HERMES_HOME` when set; otherwise `%LOCALAPPDATA%/hermes` on Windows
(falling back to `~/AppData/Local/hermes`) or `~/.hermes` on macOS/Linux.
The `/hm` entry lives under that profile's `skills/hm/SKILL.md`, and Hooks live
in its `config.yaml`. Other profiles are not synchronized automatically.

After Quickstart confirms the entry is installed, start a new Agent task so the
new entry and Hooks are discovered. If harness-mem tools are unavailable, ask
the Agent, MCP Router, plugin, or existing setup tool that manages
your MCP connection to connect harness-mem using [MCP setup](mcp-setup.md).
Keep an existing connection rather than adding a second one.

## Use it in any project

Use the entry native to your Agent:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Daily recording, background organization and task-aware recall are automatic
after setup. Users do not ask to remember each conversation. Use `hm` to
inspect or review memory:

```text
Show what has been remembered.
Correct this memory: ...
Delete the memory about ...
```

Search and review do not require working Hooks. Task-related recall uses native
context injection where supported and the Agent's MCP search otherwise. Codex
and Claude Code query on prompt submission; Hermes and Antigravity expose
pre-call events. Grok retains SessionStart/Stop because its prompt-submit output
is discarded: task queries use Agent MCP. OpenCode's system transform injects
availability, while task queries also use Agent MCP. This is not native
task-aware injection across all seven hosts.
User-level lifecycle Hooks attempt learning after each completed
reply or task: prepare the complete source, verify it, then add or update
knowledge or explicitly write nothing through the existing worker. `hm` inspects,
reviews and corrects memory; it is not the daily learning switch.
The user-level background policy applies across workspaces, while explicit
project settings take precedence. A project's `distill.autonomous.enabled=false`
opts it out. Project-specific Hook installation remains available for existing
integrations and repair. Hook installation alone does not authorize model use
or prove native execution. Unknown or edited files are preserved for Doctor or
explicit Hook repair.
An older generated Hook can also conflict after an upgrade changes the runner,
package header, or template; a conflict does not establish that the file is
unrelated. It is retained for review, including legacy Python Hooks.

Codex requires one additional user decision after the user Hooks appear:
open **Settings > Hooks**, review and trust them, then start a new task. That is
a Codex security decision; harness-mem cannot approve it for you.
Hermes also requires first-use confirmation of native shell Hooks. Quickstart
does not add allowlist approvals. Complete the selected host's native review,
trust or first-use confirmation once; then daily use needs no remembering command.

Other projects do not need another Quickstart or a separate remembering request.
Continue normal conversations; use the same global `hm` entry for review.

The approved unreleased default loads relevant current memory across all
projects at the start of later sessions. Ordinary search, `wake`, and automatic
task-aware search are not locked to the active workspace. Project information
is optional context or an explicit filter; raw conversations, job material and
legacy rows stay out of these results. Current-source and live MCP checks
passed on 2026-10-12. Published `0.9.28` does not include
this default change. Authorized background work uses the selected host CLI.
An unavailable or unsupported host is
reported instead of silently switching to Codex.

### Automatic project and session discovery (unreleased)

The Agent derives the caller workspace from native task context and supplies
it to the project check; the MCP Router's working directory is not that workspace.
For automatic discovery, `inspect_sessions {}` returns only project metadata
and session counts. Claude Code, Codex, Cursor, Grok, Hermes, OpenCode and
Antigravity use their native adapters. The Agent narrows inspection using the
returned bindings internally. Users describe the desired scope in ordinary
language, without supplying directories or session, project or batch IDs.
Project profiles are optional context labels, not name or directory authority.
Old roots in transcript source records never reserve names or force a rename.
Different roots with the same basename may use the same label. Their selected
sessions and frozen batches remain separate for file and source validation;
users do not manage directory moves, retirement or name reservations.
Existing SQLite `project_name` fields remain for compatibility, with no real
memory migration or reclassification.

Discovery is read-only: it does not import historical sessions, create jobs or
enable background work. Authorized automatic intake validates complete content,
permission and source scope before freezing revisions. A label alone cannot
authorize a source or file read. Existing manual batches remain recoverable
compatibility data for review; users do not create them to make daily memory
work. Backfilling old sessions is separate from recording new conversations.

The automatic-project probe exercises the actual MCP dispatcher, native formats,
SQLite, Notes and ordinary search using deterministic Agent decisions. The
earlier recorded revision passed 772 focused tests and five isolated outcome checks;
live MCP inventory/search/wake were checked separately. Seven live apps,
models and Hooks are outside fixture evidence; those checks do not validate the
new user-level lifecycle changes. Global host-entry instructions were not
synchronized in that earlier run because user directories were out of scope.
These additions are absent from published `0.9.28` artifacts. Current Quickstart
installs `hm` and user-level lifecycle Hooks, leaves MCP management to its
existing owner, and performs no old-session import. Background processing stays
disabled until authorized; `quickstart --confirm` supplies that authorization.

For an explicit memory filter, the current `search_memory` schema accepts
`scope="project"` with `project_name`; omitting scope means `all`. This filters
stored labels and does not establish directory ownership. `wake` also exposes
`scope="all"` by default and an explicit `project` filter.
`autopilot_search_tick` exposes task context but no scope filter; a project
context alone does not narrow its recall. Canonical descriptors and the fresh
live MCP tool list agree with these defaults. Track evidence and limits in
[the roadmap](roadmap.md#approved-simplification-labels-and-all-project-recall-2026-10-12-unreleased).

## Advanced and repair

The terminal CLI is for diagnosis, integration repair, configuration, and
explicit maintenance after initial setup:

- `harness-mem doctor` inspects a problem.
- `harness-mem integration hooks sync --client <host> --scope user` repairs
  the host's user-level lifecycle Hooks.
- `harness-mem integration hooks sync --client <host> --project-root .` repairs
  the current project's Hooks.
- `harness-mem integration commands sync --client <host>` refreshes the one
  global entry and removes old harness-mem action entries.
- `harness-mem maintenance ...` handles explicit import, export, repair, or
  cleanup. Destructive operations preview by default and require `--apply`.

### Recover a Hook upgrade conflict

From the affected project, run `harness-mem doctor`, then retry only the
affected host without force:

```bash
harness-mem integration hooks sync --client <host> --project-root .
```

If it reports `error_kind: conflict`, the conflicting file was preserved.
Confirm the project root, host and file ownership before updating. For Hermes,
also confirm the active profile in that shell; its config is shared by projects
using that profile. Compare the installed file with the current packaged
template and verified runner path. For Hermes, compare the marked
`harness-mem:begin`/`end` sections with the intended Hermes adapter commands.
Review any user edits and retain any content you still need before proceeding.

Only after that review, explicitly authorize replacement for that host:

```bash
harness-mem integration hooks sync --client <host> --project-root . --force
harness-mem integration hooks sync --client <host> --project-root .
harness-mem doctor
```

`--force` is overwrite authorization, not a guarantee of safety: generated
project Hook files are replaced in full, including user edits. Hermes replaces
its marked managed sections while retaining unrelated YAML and Hook entries;
unsupported inline YAML or incomplete markers remain errors even with force.
Antigravity likewise requires force for changed managed entries and retains
unrelated manifest entries.
Do not use `--client all --force` to clear an unexplained conflict. A successful
sync and subsequent `unchanged` result verify installation, not execution.
Doctor remains the runtime diagnostic; for Hermes also inspect the active
profile path returned by sync, since Doctor's legacy global artifact inventory
can still look under `~/.hermes`. Codex users must review and trust the changed
manifest in **Settings > Hooks**. This repair does not change MCP connections
or enable background processing.

Background processing is disabled unless you authorize it. Quickstart with
`--confirm` sets user-level `distill.autonomous.enabled=true`. Projects inherit
that policy and may override it, including `false` to opt out. Execution uses
the current supported CLI by default, or an explicitly selected Codex, Claude
Code, Hermes or OpenCode CLI via `distill.autonomous.cli`. Hosts without a
supported matching background CLI require that explicit selection. Credentials
stay in the selected CLI. Source deletion is not part of this authorization.

Source cleanup is separately opt-in and never runs merely because a session was
remembered. Before enabling it or using erasure, read
[Background memory](background-memory.md) and use the maintenance preview first.
