## Context

The repository already ships a side-by-side Storage v2 canonical store, a `SearchBackend` contract, and accepted benchmark artifacts proving those contracts exist. The remaining gap is that default runtime read/write flows still center on legacy JSON blobs plus separate SQLite indexes, while MCP search and wake reconstruct backend semantics on top of older read paths. This creates two long-term risks: truth drift between canonical and legacy stores, and retrieval drift between the backend contract and the surfaces users actually call.

## Goals / Non-Goals

**Goals:**
- Make canonical SQLite the default truth store for all structured entities and observations.
- Preserve the existing external MCP schema and wake output while changing the underlying default runtime path.
- Keep generated indexes and vector tables as derived read-path acceleration layers, not truth.
- Provide one explicit degraded runtime state when automatic bootstrap or migration fails.
- Make `SearchBackendResponse` the only authoritative runtime retrieval contract for query-aware search and wake flows.

**Non-Goals:**
- Adding new search backends such as Tantivy, LanceDB, or ANN.
- Introducing a new `deep_memory_search` or any new public MCP surface.
- Changing truth governance or allowing automatic mutation of confirmed truth.
- Rewriting the default wake renderer UX.

## Decisions

### 1. Canonical-first bootstrap lives in `LocalMemoryBackend.init()`

The backend becomes responsible for deciding whether the runtime is `canonical`, `bootstrapped_from_legacy`, or `degraded_fallback`. This keeps bootstrap semantics in one place and avoids every store deciding independently which truth source to use.

Alternative considered:
- Keep bootstrap logic in the store constructors. Rejected because structured and verbatim stores would diverge on first-run migration and degraded handling.

### 2. Canonical SQLite becomes truth, `structured_index.sqlite` and `verbatim_index.sqlite` remain derived indexes

The runtime will still use the existing `SQLiteIndex` and `HybridSearchLayer` infrastructure for FTS/vector/trigram behavior, but payload hydration moves to canonical rows. This avoids rewriting the ranking/index stack in the same iteration while still removing JSON blobs from truth semantics.

Alternative considered:
- Replace the index layer in the same slice. Rejected because it would couple truth-store cutover with retrieval engine rewrite and make regressions harder to isolate.

### 3. Degraded fallback is explicit but temporary

If canonical bootstrap or automatic migration fails, the backend records `degraded_fallback` and runs the legacy store path for compatibility. Doctor/status surfaces must report that state and point to migration or rollback actions. The fallback is a recovery mode, not a normal runtime mode.

Alternative considered:
- Hard-fail backend initialization. Rejected because existing released installations need a recoverable path.

### 4. Query-aware runtime flows consume `SearchBackendResponse` directly

`tool_search_memory`, task-aware context planning, and `context_assembly` L3/L4 stop synthesizing backend-shaped payloads from older read helpers. `read_api.search_memory` remains as a compatibility facade that delegates into the backend and rehydrates the legacy return shape from backend results.

Alternative considered:
- Keep dual search implementations and add comparison tests. Rejected because it preserves the drift the change is meant to remove.

## Risks / Trade-offs

- Bootstrap migrates more state on first use than today → Mitigation: make migration idempotent, preserve export/rollback, and expose runtime state in doctor.
- Canonical hydration touches many store methods → Mitigation: add shared canonical CRUD helpers instead of open-coding per-method SQL.
- Legacy fallback keeps some old code alive temporarily → Mitigation: confine it behind backend bootstrap state rather than scattering mode checks throughout call sites.
- Search unification may subtly change ordering or fallback metadata → Mitigation: add consistency tests across MCP search, wake packet assembly, and context assembly L3/L4.

## Migration Plan

1. Add canonical bootstrap metadata and helpers that can initialize an empty canonical store or migrate legacy payloads once.
2. Switch structured and verbatim runtime stores to canonical truth with derived index maintenance.
3. Update doctor/status to report `canonical`, `bootstrapped_from_legacy`, or `degraded_fallback`.
4. Move MCP search/wake query-aware flows to the authoritative backend contract.
5. Keep rollback/export maintenance commands available for compatibility snapshots.

Rollback strategy:
- Export canonical rows back to v5.0-compatible JSON snapshots.
- If runtime bootstrap is degraded, operators can repair or rebuild canonical storage and retry without losing legacy data.

## Open Questions

None for this slice. The change deliberately does not choose or introduce any non-SQLite backend.
