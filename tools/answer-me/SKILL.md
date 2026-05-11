---
name: answer-me
version: 0.1.0
description: |
  Optional evidence-gathering collaborator for memory drafts that lack enough code, doc, config, or test evidence.
  Use only to answer evidence gaps; promotion decisions stay in the review chain.
allowed-tools:
  - Read
  - Grep
  - Glob
---

# Answer Me

## Role

`answer-me` is an optional collaborator for evidence gathering.

It is not part of the default `session-distill` main chain and must not block the main chain when unavailable.

Use it when a memory draft is plausible but does not yet have enough supporting evidence from code, docs, config, tests, command output, or repo history.

## Main Chain Boundary

The durable memory promotion chain remains:

```text
session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only
```

`answer-me` can provide missing evidence during `memory-drafts review`, but it does not approve, reject, or sync memory entries.

## When To Use

- A draft cites a repo behavior but lacks a file or command reference.
- A conflict needs a concrete source comparison.
- A review note says the claim is under-evidenced.
- A candidate should remain local-only unless stronger evidence exists.

## Expected Output

Return a compact evidence answer with:

- direct answer
- supporting files, commands, or docs
- uncertainty or missing evidence
- whether the evidence supports `new`, `refine`, `confirm`, `conflict`, or `ephemeral`

## Non-Goals

- Do not promote memory entries.
- Do not create sync-list entries.
- Do not rewrite draft conclusions beyond evidence-scoped wording.
- Do not make `session-distill` depend on this skill.
