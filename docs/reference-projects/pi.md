# Pi

## Tracking marker

- Upstream: `earendil-works/pi`
- Local development checkout: `F:\\AIInfra\\pi`
- Reviewed branch: `main`
- Reviewed HEAD: `c1ce56d6160c5ffa81cc514fc642a139b3a001ec`
- Package markers: `@earendil-works/pi-coding-agent` 0.80.2 and
  `@earendil-works/pi-agent-core` 0.80.2
- Reviewed: 2026-08-02

The checkout is a development tree rather than a canonical mirror under
`F:\\AIInfra\\upstreams\\harness-mem`. It contained user-owned changes during
review and was inspected read-only.

## Product and architecture

Pi does not implement a separate long-term memory product. Its continuity is
the combination of an append-only session tree, context reconstruction along
the active branch, and lossy compaction checkpoints.

Two related implementations coexist:

1. `packages/agent/src/harness` exposes general `SessionStorage`,
   `SessionRepo`, session, and compaction abstractions.
2. `packages/coding-agent/src/core` contains the mature product runtime,
   including `SessionManager`, JSONL migration, branch navigation, compaction,
   and branch summarization.

They are not one canonical implementation. Leaf persistence, restored context,
and product behavior already differ, so the duplication is an architectural
warning rather than something to reproduce.

## Source evidence

- Product context reconstruction and session persistence:
  `packages/coding-agent/src/core/session-manager.ts`
- Product cut-point and compaction accounting:
  `packages/coding-agent/src/core/compaction/compaction.ts`
- Product abandoned-branch summaries:
  `packages/coding-agent/src/core/compaction/branch-summarization.ts`
- General session abstraction:
  `packages/agent/src/harness/session/`
- Parallel general compaction implementation:
  `packages/agent/src/harness/compaction/`

## Valuable invariants

### Usage-first accounting

Pi prefers provider token usage, estimates only messages beyond the last usage
record, and falls back when usage is absent. Harness-mem can reuse this ordering
without copying model-specific budgets.

### Tool-safe cut points

Pi avoids starting a retained window on a tool result and records split turns.
For harness-mem this belongs in derived semantic windows; immutable raw chunks
must remain byte-exact.

### Incremental, attributable checkpoints

Pi carries the previous summary, first retained entry, and before/after token
information. Harness-mem adapts these into content-addressed projection
lineage and read-only receipts, never durable Memory or Rule truth.

### Native branch lineage

Entry IDs, parent IDs, current leaf, fork parent, compaction boundary, and
branch-summary path can prevent abandoned branches from being mistaken for the
current task and prevent forked history from being ranked twice. This should be
preserved only by a future Pi adapter, not imposed as the cross-host store.

## Adoption decision

Adopt in 0.9.10:

- append-aware projection reuse with prefix verification;
- turn/tool-safe derived window boundaries;
- projection receipts and usage-first token accounting.

Defer:

- a read-only Pi transcript adapter and branch/fork lineage qualification;
- branch-derived TaskHandoff generation.

Reject:

- a second JSONL session or memory store;
- leaf navigation and context-overflow retry inside harness-mem;
- fixed `reserveTokens=16384` and `keepRecentTokens=20000` defaults;
- treating compaction/branch summaries as candidate-grade proof;
- copying both parallel implementations or rewriting native host history.

## Review trigger

Revisit when Pi converges its two session implementations, changes the on-disk
session schema, or harness-mem begins a qualified Pi host adapter. Until then,
track source-level invariants rather than every package patch.
