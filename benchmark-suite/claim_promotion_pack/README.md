# Claim Promotion Pack

v4.4 release-gate collection for public-claim promotion policy.

This pack makes claim wording machine-readable. It does not prove the blocked
claims. Its job is to keep bounded local readiness separate from public token
saving, broad performance, default-behavior, and code-intel runtime claims.

## Boundaries

- `token_cost_saving` stays blocked until paired token/cost deltas are positive
  from named sources.
- `true_vector_hybrid_latency` and `retrieval_recall` may be bounded local
  claims only when their source gates are ready.
- `storage_v2_speedup`, `default_reranker_hyde`, and
  `code_memory_token_runtime` stay blocked without stronger artifacts.

