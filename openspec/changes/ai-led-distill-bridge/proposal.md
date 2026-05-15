# Proposal: AI-led Distillation Bridge

## Why

AI-led distillation needs a safe bridge from Skill output into harness-mem structured memory. Regex-only extraction misses rationale and engineering decisions, but direct AI writes to active memory would let unreviewed or hallucinated entries affect `search_memory` and `wake`.

## What Changes

- Add candidate status semantics for `MemoryEntry` and `RelationFact`: `pending`, `accepted`, and `rejected`.
- Add MCP write tools that let AI suggest memory entries and relation facts without immediately activating them.
- Keep `search_memory` and `wake` scoped to accepted structured memory by default.
- Let humans promote or reject candidates through the existing CLI review loop and MCP confirm/reject tools.
- Add an import bridge for reviewed Skill JSON outputs to enter the same candidate layer.

## Impact

- Skill-driven distillation can feed harness-mem without relying on regex extraction as the main path.
- Pending and rejected AI suggestions do not pollute downstream runtime context.
- CLI remains the human review dashboard while MCP remains the runtime read/write surface.
