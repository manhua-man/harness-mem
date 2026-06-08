# Acceptance Checklist: `true_hybrid_retrieval_shootout`

Use this checklist before accepting a true-hybrid retrieval shootout result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `true_hybrid_retrieval_shootout`.
- [ ] `dataset.manifest.json` names the dataset, split, sample count, and
  public claim boundary.
- [ ] `queries.json` records every query and its `expected_source_ids`.
- [ ] Results include rows for `fts`, `vector`, and `hybrid`.
- [ ] Each row records expected and retrieved source ids.
- [ ] Each row records `recall_at_1`, `recall_at_5`, and `recall_at_10`.
- [ ] Each row records `p50_ms`, `p95_ms`, `fallback_reason`, and
  `token_cost_estimate`.
- [ ] The report includes `Retrieval Recall Claim Readiness`.
- [ ] Fixture rows are explicitly marked with `fixture_only=true`.

## Public Retrieval Recall Claim

Pass requires all of:

- [ ] Every claimed mode has `accepted=yes`.
- [ ] Every claimed mode has `fixture_only=false`.
- [ ] The dataset split and expected source oracle are named.
- [ ] The claim is limited to source-hit recall, not answer correctness.

Primary failure signals:

- Fixture-only rows are used as public retrieval recall evidence.
- Source-hit recall is described as end-to-end answer quality.
- A missing mode is hidden by an aggregate score.

## True Hybrid Latency Claim

Pass requires all of:

- [ ] The `hybrid` row executed the actual hybrid path.
- [ ] `fallback_reason` is empty for the claimed hybrid latency row.
- [ ] Cache state, hardware note, and embedding model id are recorded.

Primary failure signals:

- FTS fallback is published as true hybrid latency.
- Embedding downloads or model swaps are silent.
- Latency is reported without cache or hardware context.
