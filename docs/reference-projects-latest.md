# Reference projects — current upstream check

Checked: 2026-07-26. This is the live reference note; comparison canvases are
historical snapshots and must not be used as current version truth.

| Project | Verified upstream state | What harness-mem should keep learning |
|---|---|---|
| [claude-mem](https://github.com/thedotmack/claude-mem/releases) | v13.12.4 (2026-07-23) | Failure-isolated shutdown, migration repair that preserves orphaned user data, boot-race hardening, and producer/consumer schema alignment reinforce explicit recovery plans and content-preserving migration tests. |
| [Hindsight](https://github.com/vectorize-io/hindsight/releases) | core v0.8.5 (2026-07-22) | Recall score floors, bounded operation history, crash-retry accounting, vector coverage repair, and provider/schema failure visibility reinforce abstention metrics, backlog diagnosis, and fail-closed recovery. Integration-only tags are tracked separately from core releases. |
| [Mem0](https://github.com/mem0ai/mem0/releases) | Python SDK v2.0.14; Node SDK v3.1.2 (2026-07-25) | Explicit search error propagation, linked-memory deletion, rich filters, vector-update safety, and API compatibility remain directly relevant to deletion receipts, atomic index switching, and temporal supersede semantics. |

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
