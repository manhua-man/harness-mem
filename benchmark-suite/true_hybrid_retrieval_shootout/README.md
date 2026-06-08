# True Hybrid Retrieval Shootout

This collection is the v3.8 retrieval evidence contract. It compares:

- `fts`: SQLite FTS baseline.
- `vector`: embedding/vector baseline.
- `hybrid`: fused retrieval path.

Metrics must be reported per mode: `recall_at_1`, `recall_at_5`, `recall_at_10`,
`p50_ms`, `p95_ms`, `fallback_reason`, and `token_cost_estimate`.

Boundary: this is source-hit retrieval recall, not end-to-end answer correctness.
Fixture subsets can validate the runner contract, but public recall or latency
claims require accepted artifacts for all three modes.
