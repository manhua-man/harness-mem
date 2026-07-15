# Session Distill Sync Policy

The reviewed upstream baseline and known host-format differences are recorded
in [UPSTREAM_ALIGNMENT.md](UPSTREAM_ALIGNMENT.md).

`tools/session-distill/SKILL.md` is the harness-mem Agent specialization.
External session-distill skill suites can inform it, but harness-mem owns the
runtime lifecycle. This directory intentionally contains no executable runtime
or compatibility implementation.

## Authority

- External skill suites may contribute evidence vocabulary, audit cases, parser
  lessons, adapter fixtures, and review helper prompts.
- harness-mem owns export and review behavior.
- Internal export must target harness-mem candidate suggestion APIs.
- Durable memory writes must be governed by harness-mem auto-review and audit
  semantics.

## Allowed To Sync

- Distillation rules for stable, volatile, conflict, local-only, and ephemeral
  material.
- Coverage vocabulary and final-session review heuristics.
- Source adapter parsing lessons and fixtures for Claude, Cursor, Codex, Grok,
  Hermes, OpenCode, Antigravity, and generic JSONL.
- Guardrail test cases for partial evidence, pending candidates, raw retention, and
  self-session exclusion.
- Golden packet examples and non-sensitive fixtures.

## Not Allowed To Sync Directly

- Client-specific memory write paths such as claude-mem or Codex-local sync.
- External installation layout as the internal runtime layout.
- `memory-drafts`, session notes, or a packet workspace as a promotion gate.
- Any raw deletion behavior. Source retention is an invariant, not a guarded
  optional operation.
- Any direct confirm, reject, replace, or truth-store write behavior.

## Review Boundary

The default route is:

```text
immutable source revision -> all ordered chunks -> checkpoints
  -> final-session review -> idempotent suggest_*
  -> finalize_session_distill -> scoped auto-review + Dream -> /hm:review
```

Only `finalize_session_distill` may close a lossless job and run low-risk
auto-review. It must scope review to that job, enforce semantic promotion gates,
and expose evidence ids, policy reasons, status transitions, and a `/hm:review`
audit/undo path.
