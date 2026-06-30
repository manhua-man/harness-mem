# Session Distill Sync Policy

`tools/session-distill` is the harness-mem internal specialization. External
session-distill skill suites can inform it, but this directory is governed by
the harness-mem candidate lifecycle.

## Authority

- External skill suites may contribute packet vocabulary, audit cases, parser
  lessons, adapter fixtures, and review helper prompts.
- harness-mem owns export and review behavior.
- Internal export must target harness-mem candidate suggestion APIs.
- Durable memory writes must be governed by harness-mem auto-review and audit
  semantics.

## Allowed To Sync

- Distillation rules for stable, volatile, conflict, local-only, and ephemeral
  material.
- Packet Audit vocabulary and coverage heuristics.
- Source adapter parsing lessons for Claude, Codex, Cursor, and generic JSONL.
- Guardrail test cases for partial packets, pending drafts, raw cleanup, and
  self-session exclusion.
- Golden packet examples and non-sensitive fixtures.

## Not Allowed To Sync Directly

- Client-specific memory write paths such as claude-mem or Codex-local sync.
- External installation layout as the internal runtime layout.
- `memory-drafts` as the default promotion gate.
- Raw deletion behavior without harness-mem guardrails.
- Any direct confirm, reject, replace, or truth-store write behavior.

## Review Boundary

The default route is:

```text
raw session -> packet -> candidate draft -> suggest_* -> review preview -> /hm:review
```

By default, session-distill may suggest candidates and run low-risk auto-review
in apply mode. It must not hide durable changes: applied decisions need
evidence ids, policy reasons, status transitions, and a `/hm:review` audit/undo
path.
