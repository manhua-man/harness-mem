# Roadmap

`harness-mem` stays on the 0.8.x line for convergence, trust hardening, and
retrieval-quality proof. The stable product loop remains:

```text
wake -> search -> distill -> review
```

`dream` is the default audited maintenance side path. It must continue through
review gates and undoable audit records when durable truth changes.

## Version Line

| Version line | Goal | Ships when | Does not include |
|---|---|---|---|
| `0.8.3` | Retrieval Quality Foundation. | LLM-free golden suite covers stale truth exclusion, project leak, abstention, and vector-off fallback. | New MCP tools, wiki, search-engine swap, broad quality claims. |
| `0.8.4.x` | Trust hardening. | Superseded/current behavior is locked by contract tests; recall explain output is stable and backward compatible. | New MCP tools, wiki-as-truth, graph-native default. |
| `0.8.5.x` | Retrieval quality. | Filter-first hybrid ranking, adaptive RRF A/B, and low-confidence abstention improve the golden suite without breaking vector-off fallback. | ColBERT, graph DB, Tantivy/LanceDB default, benchmark leaderboard claims. |
| `0.8.6.x` | Maintenance closure. | Dream can produce supersede candidates through review; wake/action hints can use optional `why_it_matters` without schema pressure. | Silent truth mutation, standalone metabolism, wiki-as-truth. |
| Later / Labs | Optional acceleration and experiments. | Benchmarks prove the Python/SQLite default has a real bottleneck or quality ceiling. | Default runtime narrative or public surface expansion. |

## 0.8.4.x — Trust Hardening

- Make `current` truth the default read path and keep historical truth visible
  only through `include_history` / `deep_recall`.
- Keep `recall.steps` stable:

```text
filter -> fts -> vector -> merge -> hydrate -> context
```

- Keep score explanation additive through existing metadata:
  `fts_score`, `vector_score`, `rrf_score`, `boosts`, `confidence_tier`.
- Add regression coverage for stale truth exclusion, history opt-in,
  cross-project leak rate, abstention, and vector-off fallback.

Status: complete for the 0.8.x convergence line. Current reads exclude
`valid_to` historical truth and non-empty `superseded_by` truth, while
`include_history` / `deep_recall` remain the explicit opt-ins. Contract tests
lock `recall.steps`, temporal query abstention/conflict, MCP `deep_recall`, and
supersede audit lineage.

## 0.8.5.x — Retrieval Quality

- Strengthen filter-first ranking: project, scope, status, temporal validity,
  and supersession are hard filters before ranking.
- Evaluate adaptive IDF/RRF only through golden-suite A/B.
- Add low-confidence abstention so weak retrieval returns `partial` or empty
  instead of fabricating confidence.
- Add a lightweight 1-hop relation/decision boost without introducing a graph
  database or new public surface.

Status: complete for the local SQLite default. Filter-first search keeps
project, status, temporal, and supersession predicates ahead of ranking;
weak multi-token partial matches are filtered with
`retrieval_quality.abstention`; decision entries can receive an explainable
1-hop relation boost; and adaptive IDF/RRF work is gated by the LLM-free golden
A/B report instead of changing defaults.

## 0.8.6.x — Maintenance Closure

- Let dream emit supersede candidates, never silent truth rewrites.
- Keep review gate, state audit ledger, and undo metadata as the durable-change
  boundary.
- Add optional `why_it_matters` / action hints for wake summaries when they help
  the user act on confirmed truth.

Status: complete for the public surface. Dream records supersede candidates as
`pending_review` ledger items and leaves truth lineage unchanged until explicit
`confirm_supersede` / `reject_supersede`; wake snapshots expose optional
structured action hints; and public MCP tools are exact-allowlisted to preserve
the single memory surface.

## Later / Labs

These are not roadmap promises. They are gated experiments:

- **Optional Rust acceleration**: move hot loops such as RRF fusion, bulk index
  rebuilds, or benchmark runners into Rust only if Python becomes a measured
  bottleneck.
- **Embedding tuning**: tune or mine embeddings for harness-mem's own project
  memory distribution only if retrieval-isolated benchmarks show vector quality
  is the bottleneck.
- **Tantivy / LanceDB**: test specialized search/vector stores only if SQLite
  FTS / sqlite-vec cannot meet measured latency or quality targets.
- **Graph-native search**: keep as a lab path for richer temporal relation
  traversal. Do not make it the default truth or retrieval engine unless the
  simple 1-hop boost stops being enough under benchmarks.

## Stable Boundaries

- No wiki bridge / knowledge-cache as truth.
- No multi-profile MCP public surface.
- No standalone metabolism/reflection product surface.
- No durable write outside review or explicit confirm/reject/supersede.
- No retrieval-quality claim without retrieval-isolated tests.
