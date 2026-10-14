# Quickstart

Install `harness-mem`, run Quickstart once for the Agent app you use, then use
one memory entry in any project.

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
harness-mem quickstart
```

Quickstart identifies Codex and Claude Code directly. If it cannot identify the
current app, it stops instead of guessing. Supply the app name once:

```bash
harness-mem quickstart --client cursor
```

Quickstart installs one entry for that app: `$hm` in Codex or `/hm` in the
other supported apps. It does not inspect a project, create project files,
install project Hooks, or scan or import historical sessions. It also does not
inspect or change MCP settings.

For Hermes, run Quickstart and later Hook preparation with the same active
profile: `HERMES_HOME` when set; otherwise `%LOCALAPPDATA%/hermes` on Windows
(falling back to `~/AppData/Local/hermes`) or `~/.hermes` on macOS/Linux.
The `/hm` entry lives under that profile's `skills/hm/SKILL.md`, and Hooks live
in its `config.yaml`. Other profiles are not synchronized automatically.

After Quickstart confirms the entry is installed, start a new Agent task so the
new entry is discovered. If harness-mem tools are already available, use `hm`.
Otherwise, ask the Agent, MCP Router, plugin, or existing setup tool that manages
your MCP connection to connect harness-mem using [MCP setup](mcp-setup.md).
Keep an existing connection rather than adding a second one.

## Use it in any project

Use the entry native to your Agent:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Then say what you want:

```text
Remember this session.
How did we solve this before?
This memory is wrong.
```

Search and manual session processing do not require project setup or Hooks.
When you request automatic recording, `hm` resolves the current workspace and
installs that host's project Hooks. This is
idempotent and does not reinstall the global entry. An existing Hook file is
accepted only when it matches the current project, Hook runner, and expected
action. An unknown or edited file is preserved and the response tells you to
use Doctor or an explicit Hook repair.
An older generated Hook can also conflict after an upgrade changes the runner,
package header, or template; a conflict does not establish that the file is
unrelated. It is retained for review, including legacy Python Hooks.

Codex requires one additional user decision after those project Hooks appear:
open **Settings > Hooks**, review and trust them, then start a new task. That is
a Codex security decision; harness-mem cannot approve it for you.

Other projects do not need another Quickstart. Use the same global `hm` entry;
request automatic recording separately when you want their Hooks.

The approved unreleased default loads relevant current memory across all
projects at the start of later sessions. Ordinary search, `wake`, and automatic
task-aware search are not locked to the active workspace. Project information
is optional context or an explicit filter; raw conversations, job material and
legacy rows stay out of these results. Current-source and live MCP checks
passed on 2026-10-12. Published `0.9.28` does not include
this default change. If automatic organization is separately authorized,
completed sessions are processed in the
background with the selected host CLI. An unavailable or unsupported host is
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
enable background work. Only an explicit manual organization request prepares
the selected sources, independently revalidating their full content, permission
and source scope before freezing revisions. A label alone cannot authorize a
source or a file read. Resume uses the frozen batch's scope and
does not include new sessions. Manual batches retain sources.

The automatic-project probe exercises the actual MCP dispatcher, native formats,
SQLite, Notes and ordinary search using deterministic Agent decisions. The
current revision passed 772 focused tests and five isolated outcome checks;
live MCP inventory/search/wake were checked separately. Seven live apps,
models and Hooks are outside fixture evidence. Global host-entry instructions
were not synchronized in this run because user directories were out of scope.
These additions are absent from published `0.9.28` artifacts. Quickstart still
installs only `hm`, leaves MCP management to its existing owner, and performs
no old-session import. Background processing remains disabled by default.

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

Background processing is disabled unless you authorize it. The project setting
is `distill.autonomous.enabled=true`; it uses the current host by default, or a
project-selected Codex, Claude Code, Hermes, or OpenCode CLI. Credentials stay
in that CLI, not in harness-mem. Turn it off with
`distill.autonomous.enabled=false`.

Source cleanup is separately opt-in and never runs merely because a session was
remembered. Before enabling it or using erasure, read
[Background memory](background-memory.md) and use the maintenance preview first.
