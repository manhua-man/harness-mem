# harness-mem

**Local-first Agentic Memory RAG Runtime** for Claude Code, Codex, Cursor,
Gemini CLI, and other MCP-capable AI assistants.

`harness-mem` gives an AI assistant durable memory across sessions without
turning your project history into a cloud service. It keeps raw evidence,
proposes reviewable memory candidates, recalls confirmed truth by default, and
lets you use memory through `/hm:*`, skills, or plain language.

```text
local-first memory
+ auditable evidence
+ candidate-gated learning
+ task-aware wake context
+ progressive retrieval
+ MCP behind the curtain
```

## Current Release

Current package version is v5.0.0. v4.6-v5.0 closes the Evidence Hardening
Track on top of the v4.0.x-v4.5 foundation: artifact-backed cost/token
evidence, Storage v2 `10k/100k/1m` scale evidence, index-fabric runtime
conformance, native Rust hot-path evidence, and a machine-readable
default-change decision gate. The earlier v4.0.x-v4.5 slices still provide the
canonical SQLite store contract, Rust facade/fallback, index
fabric/SearchBackend contract, context sufficiency, memory evals, code-memory
federation, claim-promotion policy, and release-evidence packaging.

The 2026-06-16 release snapshot carries 31 accepted runs and keeps blocked
claim boundaries intact. It does not claim broad token/cost savings, public
Storage v2 speedups, ANN/Tantivy/LanceDB readiness, default reranker/HyDE
enablement, generalized Rust performance wins, or end-to-end answer-quality
gains.

## Why It Exists

AI assistants are useful until the session ends. The next session starts cold,
old decisions disappear into chat logs, and "memory" becomes folklore unless it
keeps evidence.

`harness-mem` solves that as a local runtime:

| You need | harness-mem gives you |
|---|---|
| A new session that remembers the project | Compact `wake` context with confirmed rules, handoffs, and source pointers |
| A way to preserve useful decisions | `distill` turns session history into reviewable memory candidates |
| Evidence instead of folklore | Every durable memory item points back to raw observations and source IDs |
| Search without context flooding | `search -> timeline -> observations` progressive disclosure |
| Automation without silent mutation | Low-risk review can be automated; confirmed truth still stays gated |

## Quick Start

### Install

Generic MCP client / Codex / Cursor / Gemini CLI:

```bash
pip install git+https://github.com/manhua-man/harness-mem.git
```

With optional local vector / hybrid search dependencies:

```bash
pip install "harness-mem[hybrid] @ git+https://github.com/manhua-man/harness-mem.git"
```

Claude Code users can install the repo-local plugin, slash commands, and optional
MCP registration in one pass:

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

After install:

```bash
harness-mem quickstart
harness-mem doctor
```

## Daily Use

Use slash commands when your client supports them:

```text
/hm:wake
/hm:search "release process"
/hm:distill
```

Or ask naturally:

```text
Use harness-mem to wake this project.
Search harness-mem for our release process decisions.
Distill recent sessions and summarize what was learned.
```

MCP is the transport behind the curtain. You should not need to memorize MCP
tool names for daily work.

For distillation, the assistant-facing path is:

```text
prepare_session_distill -> suggest_* -> auto_review_candidates(apply=true) -> final summary
```

## Core Workflows

### Wake

Start a task by loading compact confirmed context:

```text
/hm:wake
```

Wake is conservative. It prefers accepted/current truth, project profile,
confirmed rules, recent handoffs, and drilldown pointers. Pending candidates and
large raw evidence do not enter the default wake packet.

### Search

Ask for a topic, then expand only when needed:

```text
/hm:search "authentication decision"
```

The intended flow is:

```text
search -> timeline -> get_observations
```

Search starts compact so the assistant sees what exists before pulling long
source text into the context window.

### Distill

After meaningful work, run:

```text
/hm:distill
```

Distill ingests recent sessions, prepares evidence for the agent, writes memory
candidates, and auto-reviews low-risk items. High-risk, weak-evidence, or
ambiguous items remain reviewable instead of becoming silent truth.

### Maintain

The CLI is a local maintenance console. Current scope: CLI maintenance console (quickstart, doctor, purge, maintenance, import, config, integration).

```bash
harness-mem quickstart
harness-mem doctor
harness-mem purge -p <project-name> --before 2026-01-01 --category all --dry-run
```

Daily memory usage should stay in the assistant surface: `/hm:*`, skills, or
natural language.

## What Makes It Different

| Principle | What it means |
|---|---|
| Local-first | Memory lives on your machine under `~/.harness-mem/data/` |
| Evidence-first | Summaries never replace raw observations and provenance |
| Candidate before truth | The assistant can suggest memory; durable truth goes through review gates |
| Progressive disclosure | Start with compact recall, then open timeline and raw evidence when useful |
| Agent-facing runtime | Users interact through slash commands, skills, or natural language |
| No default daemon | Background triggers are opt-in; there is no always-on recorder by default |

当前实现已有受控自动化：conversation-level autopilot、opt-in host hook / scheduler trigger、默认关闭 Auto Dream。`triggers.*` 默认仍是 `off`。

## Capabilities

| Area | Product behavior |
|---|---|
| Cross-session memory | Observations, memory entries, rules, handoffs, relations, and project profiles |
| Wake context | Compact confirmed memory with source pointers and task-relevant recall |
| Search | SQLite FTS5 with optional local vector / hybrid retrieval |
| Evidence drilldown | Timeline and raw observation retrieval for source-backed answers |
| Candidate workflow | Suggest, review, confirm, reject, supersede, merge, and stale-truth candidates |
| Temporal truth | Current / history / as-of reads for changed decisions |
| Generated knowledge | Derived cache with source mapping; generated prose is not canonical truth |
| Skill memory | Procedural candidates and confirmed skills with explicit activation |
| Local health | Doctor and health surfaces for local state, indexes, and configuration |

## Safety Boundaries

`harness-mem` deliberately does not:

- record every turn by default
- run an always-on daemon by default
- silently mutate confirmed truth
- promote generated prose to canonical memory
- inject cross-project skills into wake by default
- require a hosted memory service
- make broad token/cost or quality claims without local evidence

## MCP Entry Point

For clients that need the raw MCP command:

```bash
python -m harness_mem.mcp.server
```

Most users should let the plugin installer or MCP client configuration own this.

## Product Docs

- [Plugin install and slash commands](./plugins/harness-mem/README.md)
- [Error codes and doctor fixes](./docs/error-codes.md)
- [Changelog](./CHANGELOG.md)

## Repository Truth Map

- `openspec/specs/`: 当前主 spec 真值
- `openspec/changes/`: 仍在进行中的 active changes
- `openspec/changes/archive/`: 已完成 change 的归档记录

Maintainer planning, benchmark artifacts, private test packets, and roadmap
material are intentionally not part of the public product narrative.
