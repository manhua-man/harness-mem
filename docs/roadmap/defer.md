# Deferred work and scope ledger

This is the current 0.9.x scope ledger. Historical 0.8.x scope-lock documents
remain release records and do not override this list.

| Item | Status | Reason / revisit rule |
|------|--------|-----------------------|
| Golden CI infrastructure + fixture expansion | shipped in 0.9.0 | Retrieval-isolated and scale coverage now gate quality claims. |
| Admission preflight / grill metadata | deferred | Keep admission in existing Skills and `govern_memory`; add runtime metadata only with measured review value. |
| Rust zero-copy parameter passing | deferred | No golden hotspot proof yet. |
| RRF algorithm tuning / adaptive IDF | deferred | Requires a measurable golden-suite win without stability loss. |
| PyPI publishing | out of product | GitHub Releases remain the canonical package channel. |
| Duplicate `mcp-router` / `mcp_router` JSON snapshots | removed in 0.9.6 | The byte-identical, unpackaged aggregate snapshots had no repository consumer and advertised stale tools. Live Router aliases remain supported. |
| `mcps/grok_com_github/**` maintenance | out of product | Not a harness-mem product surface. |
| Active docs and host-command convergence | shipped in 0.9.1 | Retired governance vocabulary is removed and generated copies are guarded against drift. |
| Deterministic offered-job distill | shipped in 0.9.3 | Optional `distill_job_id` exact targeting respects project scope, active-lane fairness, and retry backoff. Originally planned for 0.9.2. |
| Split `tool_handlers.py` by bounded capability | shipped in 0.9.3 | Read/status/dream/distill/governance bodies sit behind the existing facade; the 27-tool public allowlist is unchanged. Originally planned for 0.9.2. |
| Recovery center and memory-quality scorecard | shipped in 0.9.3 | Risk-classified Doctor actions, privacy deletion receipts, outcome quality metrics, and stuck-queue explanations ship without automatic destructive repair. |
| Terminal distill outcome and processed-source cleanup | shipped in 0.9.5 (folded from 0.9.4) | Existing jobs record promoted/no-candidate and retained/deleted/failure outcomes; raw deletion remains default-off, receipt-first, and truth-preserving. |
| Shared-container per-session deletion | deferred | Hermes/OpenCode SQLite and Antigravity shared JSONL require separately replay-tested transactional deleters; until then they report unsupported and remain untouched. |
| Candidate evidence basis + verification outcome | shipped in 0.9.5 | Evidence origin (`repository`, `user_statement`, `transcript`) remains separate from verification outcome (`verified`, `unverified`, `contradicted`, `not_applicable`). The existing candidate, finalize, Dream, event-ledger, cleanup, and status surfaces own the contract; no manual promotion gate or new MCP tool was added. See `docs/roadmap/v0.9.5-evidence-grounded-dream.md`. |
