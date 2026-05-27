---
name: ask-me
version: 0.1.0
description: |
  Optional architecture and planning consultation collaborator.
  Use for design or roadmap questions, not as a memory promotion path.
allowed-tools:
  - Read
  - Grep
  - Glob
---

# Ask Me

## Role

`ask-me` is an optional collaborator for architecture, roadmap, and implementation strategy consultation.

It is not part of the default `session-distill` main chain and must not block the main chain when unavailable.

Use it when a draft or plan raises a design question that should be resolved before changing product behavior, docs, or durable project rules.

## Main Chain Boundary

The durable memory promotion chain remains the unified MCP candidate loop:

```text
prepare_session_distill(client="auto") -> session-distill -> suggest_* -> list_candidates -> auto-review / confirm / reject -> final summary
```

`ask-me` can inform the review decision, but it does not write memory, approve candidates, or create durable output.

## When To Use

- A memory draft implies a broader architecture or roadmap decision.
- There are multiple plausible implementation paths.
- The right answer depends on product boundary, scope, or sequencing.
- A reviewer needs a short option analysis before deciding how to word a durable conclusion.

## Expected Output

Return a concise consultation note with:

- recommended option
- tradeoffs
- risks
- dependencies
- what should stay out of durable memory until verified

## Non-Goals

- Do not promote memory entries.
- Do not create candidate or durable memory entries.
- Do not turn architecture advice into memory automatically.
- Do not make `session-distill` depend on this skill.
