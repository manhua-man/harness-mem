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

## Embedding Baseline Governance

`all-MiniLM-L6-v2` remains the current benchmark default embedding baseline.
`bge-small-en-v1.5` and `nomic-embed-text-v1.5` are configurable shootout
candidates, not defaults.

Changing the default requires accepted evidence across recall, latency,
cache/disk footprint, and install-friction or cold-load/model-size concerns. A
local smoke source-hit recall run alone is not enough to change the default.
