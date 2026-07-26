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
| Bulk `mcp-router` / `mcp_router` JSON sync | frozen | These are non-canonical Router snapshots; `tool_specs.py` plus `mcps/harness_mem` are the source of truth. |
| `mcps/grok_com_github/**` maintenance | out of product | Not a harness-mem product surface. |
| Active docs and host-command convergence | shipped in 0.9.1 | Retired governance vocabulary is removed and generated copies are guarded against drift. |
| Deterministic offered-job distill | shipped in 0.9.3 | Optional `distill_job_id` exact targeting respects project scope, active-lane fairness, and retry backoff. Originally planned for 0.9.2. |
| Split `tool_handlers.py` by bounded capability | shipped in 0.9.3 | Read/status/dream/distill/governance bodies sit behind the existing facade; the 27-tool public allowlist is unchanged. Originally planned for 0.9.2. |
| Recovery center and memory-quality scorecard | shipped in 0.9.3 | Risk-classified Doctor actions, privacy deletion receipts, outcome quality metrics, and stuck-queue explanations ship without automatic destructive repair. |
