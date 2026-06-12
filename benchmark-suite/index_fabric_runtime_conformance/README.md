# Index Fabric Runtime Conformance

Benchmark id: `index_fabric_runtime_conformance`

Purpose: validate v4.0.3 `SearchBackend` response shape, manifest-last sidecar
commit, interrupted generation invisibility, lazy rebuild, and source-fingerprint
drift detection.

Claim boundary: runtime conformance smoke only. This does not prove Tantivy,
LanceDB, ANN, or production rebuild performance readiness.
