<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem logo" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center"><strong>Local-first, auditable project memory for AI Agents.</strong></p>

<p align="center"><a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="public smoke status" />
  </a>
</p>

Your Agent can read the repository, but it does not automatically retain the
decision, convention, handoff, or unfinished verification from the last ten
sessions. `harness-mem` keeps reusable project knowledge locally, so it can be
found in the next task without turning your workflow into a second knowledge
application.

## Start here

Install the release:

```bash
python -m pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  harness-mem==0.9.26
```

Then run this once from the project you want to remember:

```bash
harness-mem quickstart
```

Quickstart detects the project. It can identify Codex and Claude Code directly,
and uses an app name supplied by other hosts. If it cannot identify the current
app, it stops and asks you to run it once with `--client`, for example
`harness-mem quickstart --client cursor`; it never installs another app's files
by guessing. It installs the matching entry and verified project hooks. It does not import old sessions by default. It does not inspect or change MCP settings.
Your Agent, MCP Router, plugin, or other setup tool owns that connection. If the
Agent does not already expose harness-mem, connect it separately using
[MCP setup](docs/mcp-setup.md). Start a new task after setup.
The package is distributed through GitHub Releases, not PyPI.

For optional local vector or hybrid search, install `"harness-mem[hybrid]==0.9.26"`
from the same release index. For the complete setup and host-specific exception,
see [Quickstart](docs/quickstart.md).

## Use it every day

Use one entry in your Agent:

| Host | Entry |
|---|---|
| Codex | `$hm` |
| Claude Code, Cursor, Grok, Hermes, OpenCode, Antigravity | `/hm` |

Then say what you mean:

```text
Remember this session.
How did we solve this before?
This memory is wrong.
```

The unified entry selects the needed memory work and replies in plain language:
what was retained, what it found, or what needs correction. It does not make
you choose storage, a provider profile, or an internal workflow.

At a new session, relevant context is loaded automatically. If you separately
authorize automatic organization, completed sessions are processed in the
background through the selected host CLI; it is safe to keep working while that
happens. Background work never silently substitutes a different host CLI.

## What stays out of the way

The terminal CLI is for setup, diagnosis, integration repair, and explicit
maintenance—not everyday recall. `status`, Doctor, and maintenance are there
when something is wrong or when an operator needs to inspect or repair the
system. The underlying MCP tools, session hooks, background governance, SQLite
store, evidence checks, and audit trail remain available, but are not steps you
need to learn to remember or retrieve work.

Project memory is local by default. Evidence is checked before durable knowledge
is changed, and uncertain or unsafe source cleanup remains opt-in. Read the
[background-memory policy](docs/background-memory.md) before enabling automated
processing in a sensitive project; read the [privacy and cleanup details](docs/quickstart.md#advanced-and-repair) before any destructive maintenance.

## More detail when you need it

- [Quickstart](docs/quickstart.md) — setup, native-host notes, and recovery.
- [MCP setup](docs/mcp-setup.md) — manual or nonstandard Agent connection.
- [Cold-start demo](docs/demo-cold-start.md) — reproducible retrieval demo.
- [IDE hook adapter matrix](docs/ide-hook-adapter-matrix.md) — supported-host capability and installation evidence.
- [Memory adoption contract](docs/memory-adoption.md) — extraction, verification, assimilation, and retrieval design.
- [Roadmap](docs/roadmap.md) and [Changelog](CHANGELOG.md) — release and planned work.

## Contributors

Runtime code lives in `harness_mem/`; `code/plugins/harness-mem/` contains Agent
integration assets; `code/tools/hm-distill/SKILL.md` is an instruction-only
playbook, not a second runtime.

Run the relevant checks before contributing:

```bash
python -m compileall harness_mem
python -m ruff check harness_mem code/plugins code/tools
python -m mypy harness_mem
python -m pytest -q -m "not release_gate"
python -m pytest -q
python -m harness_mem.cli --help
cargo test --workspace
```

For user-visible runtime validation, run:

```bash
python code/tools/outcome-verifier/scripts/verify_outcomes.py \
  --config .codex/outcomes.json \
  --output .tmp/outcome-verifier/harness-mem-report.json
```

Current source package version: **0.9.26**. Latest public GitHub Release:
**0.9.26**.
