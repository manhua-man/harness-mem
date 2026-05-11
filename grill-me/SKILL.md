---
name: grill-me
version: 0.1.0
description: |
  Optional review-stage pressure test for high-risk memory drafts, project conclusions, or promotion decisions.
  Use only when the candidate conclusion needs adversarial scrutiny before it becomes durable knowledge.
allowed-tools:
  - Read
  - Grep
---

# Grill Me

## Role

`grill-me` is an optional collaborator for review-stage pressure testing.

It is not part of the default `session-distill` main chain and must not block the main chain when unavailable.

Use it when a candidate conclusion is high-risk, broad, ambiguous, or likely to become durable project guidance.

## Main Chain Boundary

The durable memory promotion chain remains:

```text
session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only
```

`grill-me` can be called during `memory-drafts review`, but it does not replace `packet-memory-export`, does not approve entries by itself, and does not write to the memory backend.

## When To Use

- A draft would change project rules, agent behavior, or user-facing guidance.
- Evidence is present but the conclusion may be overgeneralized.
- A conflict candidate needs a sharper failure-mode analysis.
- A review asks whether a conclusion is product truth, workflow preference, or local-only context.

## Expected Output

Return a short pressure-test note with:

- verdict: keep / narrow / defer / reject
- strongest evidence
- missing evidence
- likely failure modes
- proposed safer wording, if the conclusion should survive

## Non-Goals

- Do not promote memory entries.
- Do not create sync-list entries.
- Do not make `session-distill` depend on this skill.
- Do not treat lack of `grill-me` as an error.
