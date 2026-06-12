# Acceptance Checklist

- `dataset.manifest.json` records generator, seed, entry count, project count,
  entry mix, payload size, and dataset hash.
- Result rows include command, hardware, commit, p50/p95, memory, disk,
  fallback, and `claim_readiness`.
- Smoke artifacts are `release_snapshot=false` until larger release runs exist.
- The benchmark does not claim a default Storage v2 backend or public speedup.
