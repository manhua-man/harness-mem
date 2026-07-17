---
name: ask-memory-boundary
description: |
  Architecture, product-boundary, roadmap, and long-lived-rule consultation for
  harness-mem memory admission and review. Use when a candidate's truth depends
  on design judgment rather than only evidence lookup. Does not write memory.
allowed-tools:
  - Read
  - Grep
  - Glob
---

# ask-memory-boundary

## Role

Answer design-boundary questions for memory candidates.

This is the repo-local ask-me role for `harness-mem`. It helps decide how a
candidate should be scoped or worded when evidence alone is not enough:

```text
Is this a product boundary decision?
Is this architecture truth, a workflow preference, or local task context?
Should this become a repo-wide rule, module documentation, or remain pending?
What are the tradeoffs and failure modes?
```

## When To Use

Use when `grill-before-distill`, `/hm:review`, or lookback raises a design
question:

- A candidate would change future Agent behavior or repo-wide defaults.
- A memory claim implies architecture, roadmap, security, release, or product boundary truth.
- There are multiple plausible implementation or documentation paths.
- The claim may be true locally but misleading as durable project memory.
- A repeated lesson might become `govern_memory(action="suggest", kind="rule")` or repo guidance.

## Output

Return a concise consultation note:

```text
recommendation: admit | narrow | defer | reject
classification: rule | memory_entry | handoff | relation | module_doc | local_note
scope: project | module | user-preference | task-local
reasoning:
  - <tradeoff / boundary / risk>
safer_wording: <optional narrowed wording>
must_not_write_yet:
  - <items that need proof or user/product decision>
```

## Boundaries

- Do not call `suggest_*`, `confirm_*`, `reject_*`, or supersede tools.
- Do not turn architecture advice into memory automatically.
- Do not create a Trellis spec, journal, or second truth store.
- Prefer `narrow` or `defer` when the product boundary is uncertain.
- Ask the user only for preference, intent, or product direction that evidence cannot settle.
