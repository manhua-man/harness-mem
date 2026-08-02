# Evidence to roadmap

This page explains how the 0.9.7-0.9.9 plan was derived. It is deliberately
separate from the project pages: project pages describe upstream architecture;
this page records the decision boundary for harness-mem.

## Current harness-mem baseline

The following are already shipped and therefore are not new roadmap items:

| Existing capability | Local evidence | Status |
|---|---|---|
| Agent-active distill leases, backoff, and bounded refill | `harness_mem/storage/session_distill_store.py:227-462`, `harness_mem/commands/distill_lifecycle.py` | shipped; needs reconciliation/soak evidence |
| Native source cleanup and receipt states | `harness_mem/native_source_cleanup.py:97-556`, `harness_mem/processed_source_cleanup.py` | shipped; adapter replay remains incomplete |
| Storage v2 snapshot/staging/compare-before-swap | `harness_mem/storage/canonical_store.py`, `tests/test_canonical_store_migration.py` | shipped; derived-index generation is separate |
| Compact/full MCP views and drilldown | `harness_mem/mcp/response_views.py`, `harness_mem/mcp/distill_projection.py` | shipped; budget telemetry is missing |
| Two-stage semantic distill | `harness_mem/mcp/distill_handlers.py:170-230`, `tests/test_distill_projection.py` | shipped; quality needs independent fixtures |
| Scale profiles and retrieval signals | `tests/benchmarks/test_retrieval_scale.py`, `harness_mem/retrieval_signals.py` | shipped; fixture diversity and index integrity remain gaps |
| Seven-host synthetic memory test | `tests/test_cross_host_memory_e2e.py` | shipped; it bypasses real adapter scan and Dream admission |

## Upstream evidence and decision

| Evidence | Direct lesson | Harness-mem gap | Version |
|---|---|---|---|
| Hindsight worker leases and restart recovery | A stuck task needs owner, deadline, last progress, bounded recovery, and terminal reason | Chunk-level leases exist, but job-level reconciliation and soak reporting are incomplete | 0.9.7 |
| MemoryData and LongMemEval runners | Missing/unsupported cases must be `skipped`/`error`, while retrieval, answer, and abstention are separate metrics | Existing 60-case fixture is mostly a generated matrix; it lacks enough independent long-session task shapes and per-query artifacts | 0.9.7 |
| LoCoMo sessions | Cross-session temporal facts need replayable multi-session fixtures | Current golden cases do not sufficiently cover temporal synthesis across session boundaries | 0.9.7 |
| Graphiti temporal edges | Validity/invalidation is a data and filter concern, not only ranking | Existing current-only filtering needs richer as-of and exclusion reason coverage | 0.9.7 |
| sqlite-vec mutation checks | Batch-derived rows need membership, dimension, and deletion invariants tied to canonical generation | vec0, embedding, and trigram rebuilds need a shared publish contract; incremental FTS/relation updates need transaction contracts | 0.9.8 |
| Tantivy prepare/commit/rollback | Readers must see either old or new complete batch generation | Rebuild fault-injection and active-generation fallback need one shared contract without replacing SQLite trigger indexes | 0.9.8 |
| Letta compaction tests | Context compression should expose budget and fallback outcome rather than silently overwrite | Compact output exists, but raw/summary/retrieved budget accounting is not a stable internal contract | 0.9.8 |
| BEAM adapter contract | Update/delete/reset and unsupported capabilities are executable behavior contracts; failures produce artifacts | Existing host test is synthetic and does not qualify adapter capability or failure rows | 0.9.9 |
| claude-mem outbox/health lifecycle | Durable work state must survive delivery failure and startup/shutdown races | Native adapter replay and operator repair need an end-to-end qualification matrix | 0.9.9 |
| Mem0 scoped/paginated deletion | Deletion must be scoped, complete across pages, and compatibility-tested | Native cleanup ownership and upgrade/restore matrix need real host fixtures | 0.9.9 |
| smartsearch source/fallback traces | Answer, evidence, degraded fallback, and hard failure should be distinguishable | Retrieval signals exist, but full evidence/attempt trace needs stable rendering and replay tests | 0.9.9 |

## Dependency graph

```text
0.9.7 fixtures + lifecycle reconciliation
        |
        v
0.9.8 index generations + context budget contracts
        |
        v
0.9.9 real adapter replay + install/upgrade qualification
```

The order prevents a host replay from becoming a visual smoke test with no
quality baseline, and prevents index hardening from being judged only by
latency. Every version keeps the existing `wake -> search -> distill -> review
-> dream` loop, exactly 27 public MCP tools, one local SQLite truth path, and
Agent-mediated semantic work.

## Rejected alternatives

- Redis/BullMQ or a permanent semantic worker: useful upstream patterns, but a
  deployment expansion that conflicts with the local Agent-active boundary.
- Graph database or Tantivy replacement: upstream architecture is informative;
  current evidence does not show SQLite is the quality bottleneck.
- External LLM judge or benchmark services in CI: useful for research, but not
  deterministic release gates.
- New public MCP tools: all lessons fit internal schemas, existing full views,
  maintenance commands, and test artifacts.
