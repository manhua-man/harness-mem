# Quickstart

This is the only setup path most people need. Install `harness-mem`, run one
command in a project, then use one native entry in your Agent.

## Install once

Install the release:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  harness-mem==0.9.26
```

The package is distributed through GitHub Releases rather than PyPI. The release
index selects the compatible native wheel. Optional local vector or hybrid
search dependencies use the same index:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  "harness-mem[hybrid]==0.9.26"
```

From the project you want to remember, run:

```bash
harness-mem quickstart
```

Quickstart detects the current project. It can identify Codex and Claude Code
directly, and uses `HARNESS_MEM_CLIENT` when another host supplies it. If the
current app cannot be identified, Quickstart stops without installing another
app's files. Run it again with the app name, for example:

```bash
harness-mem quickstart --client cursor
```

Quickstart installs the matching native entry and project Hook files, and does
not import historical sessions by default. An existing dedicated Hook file is
accepted only when it matches the current project, Hook runner, and expected
action. An unknown or edited file is preserved and setup stops; use Doctor to
inspect it, then run an explicit repair only if you intend to replace it.
Quickstart does not inspect or change MCP settings. The Agent, MCP Router,
plugin, or other setup tool owns that connection. If harness-mem is not already
available in the Agent, connect it separately using [MCP setup](mcp-setup.md).
Then start a new Agent task.

In Codex, native command hooks require one additional approval: open **Settings
> Hooks**, review and trust the project hooks, then start a new task. This is a
Codex security decision, not a command that harness-mem can make for you.

## Use one entry

After Quickstart, use the entry native to your Agent:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Use ordinary language:

```text
Remember this session.
How did we solve this before?
This memory is wrong.
```

The entry determines whether to retain, retrieve, or correct memory and returns
a short human-readable result. It will not ask you to pick a storage backend,
provider profile, or internal action name for ordinary work.

Relevant project context is loaded at the start of a new session. If automatic
organization is separately authorized, completed sessions are processed
in the background with the selected host CLI. That work may be queued or need
attention; it is never reported as completed until the local evidence and write
checks have passed. An unavailable or unsupported host is reported instead of
falling back to Codex.

## Advanced and repair

`harness-mem` is an operator CLI outside this initial setup: use it for diagnosis,
integration repair, configuration, and explicit maintenance. In particular:

- `status` and `harness-mem doctor` are for understanding a problem.
- `harness-mem integration ...` is for a failed or nonstandard installation.
- `harness-mem maintenance ...` is for explicit import, export, repair, or
  cleanup. Destructive operations preview by default and require `--apply`.

The normal path hides, but does not remove, the MCP surface, hooks, background
governance, evidence, and SQLite current-knowledge store. Use these references
when you need their details:

- [MCP setup](mcp-setup.md) for a manual or nonstandard client connection.
- [IDE hook adapter matrix](ide-hook-adapter-matrix.md) for host capability and
  hook-installation evidence.
- [Background memory](background-memory.md) for authorization, selected CLI,
  receipts, and privacy boundaries.
- [Memory adoption contract](memory-adoption.md) for the extraction,
  verification, assimilation, and retrieval design.

Background processing is disabled unless you authorize it. The project setting
is `distill.autonomous.enabled=true`; it uses the current host by default, or a
project-selected Codex, Claude Code, Hermes, or OpenCode CLI. Credentials stay
in that CLI, not in harness-mem. Turn it off with
`distill.autonomous.enabled=false`. Do not enable it for a project until you are
comfortable with that host CLI processing retained local session material.

Source cleanup is separately opt-in and never runs just because a session was
remembered. Before enabling it or using erasure, read the cleanup and privacy
rules in [background memory](background-memory.md) and use the maintenance
preview first.
