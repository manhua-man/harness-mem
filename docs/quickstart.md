# Quickstart

Install `harness-mem`, run Quickstart once for the Agent app you use, then use
one memory entry in any project.

## Install once

Install the release:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.27 \
  harness-mem==0.9.27
```

The package is distributed through GitHub Releases rather than PyPI. Optional
local vector or hybrid search dependencies use the same index:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.27 \
  "harness-mem[hybrid]==0.9.27"
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
inspect or change MCP settings. The Agent, MCP Router, plugin, or other setup
tool that owns the MCP connection remains responsible for it. If harness-mem is
not already available in the Agent, follow [MCP setup](mcp-setup.md).

Start a new Agent task after Quickstart so the new entry is discovered.

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

On the first use in a project, `hm` resolves the current workspace, prepares
its local project memory, and installs that host's project Hooks. This is
idempotent and does not reinstall the global entry. An existing Hook file is
accepted only when it matches the current project, Hook runner, and expected
action. An unknown or edited file is preserved and the response tells you to
use Doctor or an explicit Hook repair.

Codex requires one additional user decision after those project Hooks appear:
open **Settings > Hooks**, review and trust them, then start a new task. That is
a Codex security decision; harness-mem cannot approve it for you.

Other projects do not need another Quickstart. Use the same global `hm` entry;
the first use prepares each project separately.

Relevant project context is loaded at the start of later sessions. If automatic
organization is separately authorized, completed sessions are processed in the
background with the selected host CLI. An unavailable or unsupported host is
reported instead of silently switching to Codex.

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

Background processing is disabled unless you authorize it. The project setting
is `distill.autonomous.enabled=true`; it uses the current host by default, or a
project-selected Codex, Claude Code, Hermes, or OpenCode CLI. Credentials stay
in that CLI, not in harness-mem. Turn it off with
`distill.autonomous.enabled=false`.

Source cleanup is separately opt-in and never runs merely because a session was
remembered. Before enabling it or using erasure, read
[Background memory](background-memory.md) and use the maintenance preview first.
