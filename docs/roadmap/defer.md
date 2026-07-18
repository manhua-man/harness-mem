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
| Active docs and host-command convergence | 0.9.1 | Remove retired governance vocabulary and guard generated copies against drift. |
| Split `tool_handlers.py` by bounded capability | deferred | Do only behind public-surface and handler-boundary tests; no 0.9.1 behavior change. |
