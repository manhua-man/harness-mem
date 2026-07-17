# Reference projects — current upstream check

Checked: 2026-07-18. This is the live reference note; comparison canvases are
historical snapshots and must not be used as current version truth.

| Project | Verified upstream state | What harness-mem should keep learning |
|---|---|---|
| [claude-mem](https://github.com/thedotmack/claude-mem/releases) | v13.11.0 (2026-07-13) | Worker-native background sync, bounded pages/backoff, cross-platform host correctness, and automatic recovery. Its latest release reinforces failure-isolated backlog processing rather than more user commands. |
| [Hindsight](https://github.com/vectorize-io/hindsight/releases) | v0.8.4 (2026-07-01) | Retain/recall/reflect simplicity, idempotent chunking, worker operation metrics, temporal/entity extraction, and published long-memory evaluation. harness-mem should compare measured retrieval behavior, not copy its service/graph footprint. |
| [Mem0](https://github.com/mem0ai/mem0/releases) | Python SDK v2.0.12; Node SDK v3.1.0 (2026-07-13) | Linked-memory deletion, rich filters, URL-safe identifiers, vector-update rollback, and explicit API compatibility are directly relevant to privacy lifecycle, atomic index switching, and temporal supersede semantics. |

Changes adopted in the current workspace from this refresh:

- pre-persistence `<private>` redaction and project capture-ignore policy;
- configurable transcript retention plus complete hard-delete planning/apply;
- bounded, failure-isolated Agent-active distill with 3:1 recent/oldest refill,
  a daily new-job budget, and failure backoff;
- repository-version conflict filtering across Observation, L1 truth, and L2 handoff;
- 60 deterministic retrieval-isolated cases and seven-host transcript-to-wake coverage;
- one composite `govern_memory` MCP write surface instead of 15 public low-level
  suggest/confirm/reject tools.

Deliberately not copied: mandatory cloud sync, a graph database, a browser UI,
or a second knowledge/wiki product. Those expand the product boundary without
fixing the current local correctness and lifecycle priorities.
