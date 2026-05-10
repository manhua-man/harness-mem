# PRD 02: Roadmap

This roadmap reconciles the v1.3/v1.4 reviews with the current repository direction. The detailed historical proposal remains in `roadmap-v13-v14-proposal.md`.

## Priority Principle

Order work by impact:

1. User-visible value before internal cleanup.
2. Stability before new features.
3. Documentation truth before code refactors when reviews reveal stale or misleading status.

## v1.3: V1 Reliability Closure

Source: `review-eng-v13-v14.md`, `review-health-v13-v14.md`, `review-cli-v13-v14.md`.

The engineering review recommended vector search and a hybrid layer because pure FTS had a semantic recall gap. That path has since become the main retrieval direction, so remaining v1.3 work should not reopen basic hybrid search as a new feature. It should close the daily loop:

- Keep `search --mode auto|fts|hybrid` reliable and fallback-safe.
- Harden `correct` and `handoff` CLI validation because they are core-loop commands.
- Keep storage tests direct and current.
- Refresh quality gate numbers after every release candidate.

## v1.4: Memory Maintenance

Source: `review-eng-v13-v14.md`.

After retrieval is stable, v1.4 should focus on memory quality and long-term maintenance:

- Compaction/purging: `purge` already marks old observations and structured memory as compacted without destroying blob truth; `cmd_purge` is now split into `commands/purge.py`, and `MemoryEntry` now tracks `usage_count` / `last_accessed_at` with a doctor quality summary. Broader automatic cleanup policy remains open.
- Relation facts: the lightweight `RelationFact` schema, SQLite/local structured-store slice, CLI/MCP search output, conservative distill write path, and wake-up injection have landed with tests. The remaining decision is benchmark-based: whether relation facts improve recall or wake-up usefulness enough to justify expanding extraction quality.
- Temporal bias: hybrid search now has CLI, MCP, and REST opt-in switches for temporal tie-breaking; keep it disabled by default until benchmark evidence proves it improves temporal reasoning without hiding older but more relevant memories.

The engineering review explicitly warned against adding graph DBs, Redis caches, external vector databases, or rerankers into v1.x. Keep the local-first JSON + SQLite model unless benchmark evidence justifies a change.

## v1.5: Platform Expansion

New adapters such as Cursor or Gemini CLI should wait until the current V1 loop and quality gates are consistently green. Platform breadth is valuable only when the shared memory runtime is trustworthy.
