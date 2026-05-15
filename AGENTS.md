---
description: AI Agent guide - memory system architecture, responsibilities, and collaboration truth
alwaysApply: true
---

# AGENTS.md (Facts)

> This file defines the core operating logic for **harness-mem**.
> Unlike a traditional search tool, this project is an **AI-led memory runtime**.

## Core Architecture: AI-Centered Workflow

| Role | Best Practice |
| :--- | :--- |
| **AI (operator / backend)** | Use **Skill** workflows such as `tools/session-distill` to batch-read old sessions and perform high-quality distillation. |
| **AI (operator / inline)** | Use **MCP** `suggest_rule` / `suggest_memory_entry` to record immediate rules and knowledge candidates. |
| **Human (reviewer)** | Use **CLI** `candidates` / `confirm` / `reject` to review candidate memories. |
| **AI (consumer)** | Use **MCP** `search_memory` / `wake` to read confirmed memories. |

Principle: **Skills handle heavy cognitive batch work, MCP provides the runtime read/write interface, and CLI is the human review dashboard.** AI-distilled or inline-recorded content should enter the candidate layer first, then become stable memory consumable by `search_memory` / `wake` only after human confirmation.

---

## AI Collaboration Protocol

### 1. Distillation
- **Trigger**: when a development phase ends or many raw sessions / observations accumulate, start a dedicated Skill such as `tools/session-distill` instead of asking the everyday coding agent to perform long-context distillation inline.
- **AI task**: as the dedicated operator, read raw logs and identify reusable technical decisions, collaboration rules, task state, and rationale instead of matching keywords mechanically.
- **Boundary**: the long-form path is `session-distill -> packet-memory-export -> memory-drafts review -> candidate layer`. Skills understand and filter; `harness-mem` persists structured candidates and serves confirmed memory later.
- **Persistence**: distilled output enters the candidate layer first, such as `RuleCandidate`, pending `MemoryEntry`, or pending `RelationFact`. Only confirmed candidates should become stable structured memory.

### 2. Runtime Access
- **Search first**: before working, agents should use MCP `search_memory` when historical context may matter.
- **Inline capture**: when a new convention, fact, or correction appears during normal work, agents should use MCP `suggest_rule` / `suggest_memory_entry` rather than waiting for batch distillation.
- **Consumption boundary**: `search_memory` / `wake` should consume confirmed memory by default; pending candidates are for review and should not pollute wake context.

### 3. Human Confirmation
- Unconfirmed memory stays in candidate status. Agents should tell the user when candidates were created and point them to `harness-mem candidates`, `harness-mem confirm <id>`, and `harness-mem reject <id>`.

### 4. Regex Distill Positioning
- `harness-mem distill` / `harness-mem ds` is a heuristic fallback for quick smoke checks, low-cost offline scanning, or environments where AI Skills are unavailable.
- Do not treat regex extraction as the long-term primary distillation engine. High-quality memory should be produced by AI Skills and enter structured storage through the candidate review path.

---

## Repository Map

| Path | Purpose | Priority |
|------|---------|----------|
| `harness_mem/` | Python runtime: schemas, storage, search, MCP server, CLI commands. | Core implementation |
| `tools/session-distill/` | Long-form distillation Skill: raw session -> packet -> memory drafts. | Core workflow |
| `tools/mem-distill/` | Cleanup, dedupe, and consolidation for existing memory / observations. | Organizer |
| `tools/grill-me/` / `tools/answer-me/` / `tools/ask-me/` | Optional review collaborators, not hard dependencies. | Optional |
| `plugins/harness-mem/` | Repo-local plugin wrapper: install, MCP config, skill entry. | Integration |
| `docs/` | Docs index, design notes, reviews, best practices. | Reference |
| `openspec/` | Specs and change records; capability or behavior changes should be recorded here. | Design truth |
| `tests/` | Product tests: CLI, MCP, storage, search, integration. | Validation |
| `benchmarks/` | Product benchmark scripts and results. | Performance validation |

---

## Common Commands

```bash
# diagnostics and status
harness-mem doctor
harness-mem status
harness-mem quickstart

# human memory review
harness-mem candidates
harness-mem confirm <id>
harness-mem reject <id>

# heuristic fallback, not the high-quality distillation path
harness-mem ds

# runtime consumption checks
harness-mem wake
harness-mem search "auth logic"
```

## Key Technologies

- **Runtime**: Python 3.13+
- **Database**: SQLite FTS5 verbatim index + JSON blobs / JSONL-style structured memory
- **Integration**: MCP (Model Context Protocol) + GStack / Codex / Claude Skills
- **Primary workflow**: Skill-driven distillation, CLI human review, MCP runtime consumption
