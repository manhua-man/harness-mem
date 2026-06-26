<p align="center">
  <img src="docs/assets/harness-mem-logo.svg" alt="harness-mem logo" width="420" />
</p>

<h1 align="center">harness-mem</h1>

<p align="center">
  <strong>Local-first, auditable, pluggable memory backend for AI Agents.</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml">
    <img src="https://github.com/manhua-man/harness-mem/actions/workflows/public-smoke.yml/badge.svg" alt="public smoke status" />
  </a>
</p>

AI Agents can read your repo, but they usually do not know what happened in the
last ten sessions: release boundaries, decisions, handoffs, review outcomes,
and "do not claim this yet" rules.

`harness-mem` turns that project memory into a local backend exposed through
MCP. Codex, Claude Code, Cursor, Gemini CLI, and other Agent clients can recover
context with `wake` and `search`, then propose new memory through `distill`.
Nothing becomes durable truth until it passes review.

<p align="center">
  <img src="docs/assets/harness-mem-cold-start-flow.svg" alt="A fresh Agent uses wake, search, distill, and review against a local auditable memory backend" width="900" />
</p>

## Core Loop

```text
wake -> search -> distill -> review
```

| Step | Job |
|---|---|
| `wake` | Load a compact project brief from confirmed memory. |
| `search` | Retrieve prior decisions, rules, and handoffs with sources. |
| `distill` | Turn recent session evidence into memory candidates and preview review decisions. |
| `review` | Confirm, reject, supersede, or keep candidates pending. |

## Why It Is Different

- Local-first: project memory stays on your machine by default.
- Agent-ready: MCP is the normal integration path for coding tools.
- Reviewable: Agents suggest memory; confirmed memory is a separate layer.
- Pluggable: use it from Codex, Claude Code, Cursor, Gemini CLI, or any MCP-capable Agent client.

<p align="center">
  <img src="docs/assets/harness-mem-candidate-governance.svg" alt="candidate-before-truth memory governance state machine" width="900" />
</p>

`harness-mem` stays behind the Agent client. MCP is the transport; the runtime
owns storage, candidates, review, retrieval, and local audit state.

<p align="center">
  <img src="docs/assets/harness-mem-runtime-layered-architecture.svg" alt="harness-mem runtime layered architecture" width="900" />
</p>

## Install

```bash
pip install git+https://github.com/manhua-man/harness-mem.git
```

Optional local vector / hybrid search dependencies:

```bash
pip install "harness-mem[hybrid] @ git+https://github.com/manhua-man/harness-mem.git"
```

Claude Code users can install the repo-local plugin and optionally register MCP:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

Then use the Agent-facing commands:

```text
/hm:status
/hm:wake
/hm:search "release boundary"
/hm:distill <project> 10
/hm:review
```

The terminal CLI is an operator console, not the daily memory workflow. Its
top-level surface is `init`, `quickstart`/`qs`, `doctor`, `config`,
`integration`, and `maintenance`; import and purge operations live under
`harness-mem maintenance ...` and default to dry-run previews.

## Repository

- `harness_mem/`: runtime package.
- `plugins/harness-mem/`: Agent client integration.
- `tools/session-distill/`: reference session distillation skill.
- `docs/quickstart.md`: minimal setup path.
- `docs/mcp-setup.md`: MCP setup notes.
- `docs/demo-cold-start.md`: reproducible cold-start demo.
- `docs/assets/`: logo and public README diagrams.

## Documentation

- [Quickstart](docs/quickstart.md)
- [MCP setup](docs/mcp-setup.md)
- [Cold-start demo](docs/demo-cold-start.md)
- [Recall audit contract](docs/recall-audit.md)
- [Causal benchmark smoke](docs/causal-benchmark.md)
- [Changelog](CHANGELOG.md)

## Development Check

```bash
python -m compileall harness_mem
python -m ruff check harness_mem plugins tools
python -m harness_mem.cli --help
cargo test --workspace
```

Current package version: **0.8.2**.
