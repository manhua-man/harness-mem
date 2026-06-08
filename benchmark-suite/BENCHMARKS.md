# Benchmark Collections

This file defines the benchmark collections we want to keep long-term.
For executable coverage gaps, see [GAPS.md](./GAPS.md).

Each collection has:

- a stable benchmark id
- a concrete goal
- fixed metrics
- artifact requirements
- a publish rule

## Coverage dimensions

These are the product-level dimensions we use when deciding whether benchmark
coverage is complete enough to support a public claim.

Repeated labels such as `Memory` / `Memory runtime`, `Evidence` /
`Evidence safety`, `Generated` / `Generated knowledge`, `Temporal` /
`Temporal query`, and `Auto Maint` / `Auto maintenance` are treated as the same
dimension.

| Dimension | Current benchmark coverage | Current status | Next benchmark action |
|---|---|---|---|
| Memory runtime | `retrieval_quality_longmemeval`, `retrieval_diagnostics`, `client_enabled_vs_disabled` | `client_enabled_vs_disabled` has a completed 3-task paired artifact; it proves task correctness and memory-call gating, not memory-retrieval uplift. | Re-run with `token_usage.available=true` on both sides before public token/cost/time-savings claims. |
| Evidence safety | `evidence_safety`, `client_trace_evidence` | `evidence_safety` has a completed E1-E5 guarded artifact with overclaim and abstention pressure. | Expand only if a new evidence boundary is added; do not generalize beyond the exact task set. |
| Generated knowledge | `generated_knowledge_freshness` | v3.2 surfaces shipped and GK1-GK5 completed with source-map, freshness, generated-only, invalidation, and citation-laundering checks. | Keep generated prose out of confirmed truth; use future runs for claims-first/source-map coverage improvements. |
| Temporal query | `temporal_product_query`, `retrieval_quality_longmemeval`, `retrieval_diagnostics` | TQ1-TQ5 completed for current/history/as_of/supersede/ambiguity behavior; LongMemEval remains retrieval-quality evidence. | Use product temporal artifacts for product claims; use LongMemEval for retrieval claims. |
| Auto maintenance | `auto_maintenance_effectiveness`, `maintenance_recovery` | v3.1 `/hm:dream` surfaces shipped and AM1-AM6 completed for merge/stale/supersede/reject/undo/ledger behavior. | Do not claim production long-run precision/recall without a live maintenance benchmark. |
| Observability | `runtime_health_observability`, `maintenance_recovery`, `client_trace_evidence` | v3.4.4 runtime health/cost/regression surfaces shipped and RH1-RH6 completed, including false-success accounting. | Cloud telemetry and real billing are out of scope unless a separate benchmark is added. |
| Cost discipline | `client_enabled_vs_disabled`, `runtime_health_observability` | Cost surfaces and budget-overrun detection are covered; the 2026-06-09 token-observed pair has named token totals but a negative saving delta. | No public token-saving claim until a paired run reports a positive disabled-minus-enabled token/cost delta from a named source. |
| Performance | `latency_warm_path`, `true_hybrid_retrieval_shootout`, `retrieval_quality_longmemeval` | Non-smoke warm-path FTS/wake run completed; the 2026-06-09 true-hybrid probe ran with `effective_mode=hybrid` and no fallback. | Keep true-hybrid latency claims scoped to the local synthetic fixture unless a broader dataset/hardware run is added. |
| Retrieval recall | `true_hybrid_retrieval_shootout`, `retrieval_quality_longmemeval`, `retrieval_diagnostics` | v3.8 has fixture-contract rows plus a local smoke source-hit recall artifact across FTS/vector/hybrid. `claim_readiness.retrieval_recall.ready` is true for that bounded local split. | Do not present source-hit recall as end-to-end answer correctness or broad corpus quality. |

Coverage levels:

- **Result**: completed run artifacts exist and can support a bounded claim.
- **Smoke**: scaffold or driver proved shape only; do not cite as a product
  result.
- **Methodology**: benchmark design exists; do not cite it as a product result
  until artifact-backed outputs exist.
- **Test / planning only**: regression tests or roadmap docs exist, but no
  benchmark claim is supported.

Completed result summary:

- See [RESULTS.md](./RESULTS.md) for artifact-backed metrics and bounded claims.
- See [GAPS.md](./GAPS.md) for closure evidence for BENCH-001 through
  BENCH-007.
- BENCH-008 is tracked in [RESULTS.md](./RESULTS.md) as a v3.8 fixture
  contract for true-hybrid retrieval evidence shape; it is not a public recall
  claim.

## B1. Retrieval Quality

Benchmark id: `retrieval_quality_longmemeval`

Goal:

- measure retrieval quality on the current retrieval stack
- keep a durable baseline for future non-regression work

Core tasks:

- full LongMemEval replay
- per-question-type breakdown
- top-k comparison when needed

Metrics:

- `avg_recall_at_5`
- per-type `recall_at_5`
- `perfect_rate`
- `partial_rate`
- `zero_rate`
- total runtime
- per-question runtime

Artifacts:

- raw result JSON
- exact dataset path
- exact command line
- environment note
- short markdown report

Publish rule:

- may be cited publicly only with the exact mode and exact split used

## B2. Retrieval Diagnostics

Benchmark id: `retrieval_diagnostics`

Goal:

- explain why retrieval changed
- localize gains or regressions to fusion, stem fallback, temporal handling, or
  candidate ordering

Core tasks:

- fusion ablation
- stem fallback comparison
- temporal comparison
- failure bucket analysis

Metrics:

- delta versus baseline recall
- per-type delta
- representative failure buckets
- latency delta per mode

Artifacts:

- comparison JSON
- failure analysis markdown
- script inputs
- representative misses

Publish rule:

- maintainer-facing by default; public use only after reduction into a simpler
  product claim

## B3. Warm Path Latency

Benchmark id: `latency_warm_path`

Goal:

- measure warm-path operational latency for the memory runtime
- keep latency claims separate from retrieval quality claims

Core tasks:

- wake synthetic latency
- search FTS latency
- search hybrid latency
- optional doctor latency sample

Metrics:

- `p50_ms`
- `p95_ms`
- `max_ms`
- cold/warm note
- dataset size or corpus size

Artifacts:

- raw measurements
- benchmark driver parameters
- warm-up policy note

Publish rule:

- any public latency statement must say whether it is synthetic, cold, or warm
- any vector-hybrid latency statement must come from a rendered report whose
  `Vector Hybrid Claim Readiness` section says `True vector-hybrid claim ready:
  yes`

## B4. Client Continuation Value

Benchmark id: `client_enabled_vs_disabled`

Goal:

- measure whether `harness-mem` saves real work in continuation tasks

Core tasks:

- repo truth recovery
- release-truth recovery
- design-constraint recovery
- operational workflow recovery
- optional negative-control task

Metrics:

- total runtime
- total turns
- follow-up count
- token total and `token_usage` source if visible
- accepted pass/fail
- delta between enabled and disabled conditions

Artifacts:

- prompt text
- client-facing transcript
- tool call record if visible
- final answer
- acceptance judgment
- paired result JSON

Publish rule:

- this is the primary benchmark required before public token/cost savings claims

## B5. Client Trace Evidence

Benchmark id: `client_trace_evidence`

Goal:

- capture user-visible evidence that the runtime behaves correctly in actual
  clients

Core tasks:

- cross-client write/read trace
- workspace-path-visible packet run
- transport failure transcript
- mismatch clarification transcript

Metrics:

- success/failure
- expected phrase surfaced
- correct guidance surfaced
- forbidden guidance absent

Artifacts:

- full transcript
- workspace path if relevant
- tool call list if visible
- final user-visible output

Publish rule:

- never convert near-neighbor evidence into stronger transcript claims

## B6. Maintenance Recovery

Benchmark id: `maintenance_recovery`

Goal:

- measure the operational recovery path for broken or stale state

Core tasks:

- doctor diagnosis
- rebuild-vector-index recovery
- vector-mismatch detection
- missing-cache or missing-transport handling

Metrics:

- diagnosis surfaced or not
- runtime to diagnosis
- recovery success
- false-success count

Artifacts:

- input state description
- command transcript
- before/after state
- recovery notes

Publish rule:

- maintainer-facing unless turned into a user-facing support claim

## B7. Evidence Safety

Benchmark id: `evidence_safety`

Goal:

- measure whether the agent keeps evidence strength honest
- prevent generated-only, near-neighbor, missing-source, or historical evidence
  from becoming overstrong claims

Core tasks:

- missing source id boundary
- generated-only material boundary
- near-neighbor packet evidence
- historical superseded truth
- insufficient-evidence abstention

Metrics:

- accepted pass/fail
- overclaim count
- abstention correctness
- concrete evidence cited or missing
- runtime

Artifacts:

- prompt text
- transcript
- tool call record if visible
- final answer
- acceptance judgment

Publish rule:

- may be cited only as evidence-safety behavior for the exact task set; do not
  generalize to all agent quality

## B8. Temporal Product Query

Benchmark id: `temporal_product_query`

Goal:

- measure product-level temporal query boundaries
- keep current truth, historical truth, `as_of` scope, supersede chains, and
  abstention behavior separate

Core tasks:

- default current-only read
- explicit history request
- `as_of` boundary
- supersede timeline
- ambiguous temporal scope

Metrics:

- accepted pass/fail
- current/history confusion count
- abstention correctness
- source-backed temporal evidence
- runtime

Artifacts:

- prompt text
- transcript
- tool call record if visible
- final answer
- acceptance judgment

Publish rule:

- LongMemEval temporal-reasoning is retrieval evidence; product temporal-query
  claims require this benchmark or equivalent artifacts

## B9. Generated Knowledge Freshness

Benchmark id: `generated_knowledge_freshness`

Goal:

- measure generated knowledge source-map completeness, freshness, invalidation,
  and citation support

Core tasks:

- source-map completeness
- generated-only claim boundary
- freshness detection
- incremental invalidation
- citation validation

Metrics:

- accepted pass/fail
- unsupported generated claim count
- stale-cache detection
- source-map coverage
- citation-support failure count

Artifacts:

- prompt text
- transcript
- source-map artifact or note
- final answer
- acceptance judgment

Publish rule:

- completed artifacts may be cited only as generated-knowledge boundary
  evidence; generated prose must never be reported as confirmed truth

## B10. Auto Maintenance Effectiveness

Benchmark id: `auto_maintenance_effectiveness`

Goal:

- measure whether opt-in automatic maintenance improves memory state without
  silent truth mutation or irrecoverable false positives

Core tasks:

- duplicate merge suggestion
- stale truth suggestion
- supersede suggestion
- false-positive rejection
- undo / rollback
- ledger explainability

Metrics:

- accepted pass/fail
- true positive count
- false positive count
- false success count
- undo success
- audit/ledger completeness

Artifacts:

- prompt text
- transcript
- before/after state
- ledger or audit notes
- acceptance judgment

Publish rule:

- requires a completed artifact bundle before any public effectiveness claim; no
  public claim may imply silent confirmed-truth mutation

## B11. Runtime Health Observability

Benchmark id: `runtime_health_observability`

Goal:

- measure local runtime health, version drift, cost discipline, regression
  gates, transport diagnosis, and false-success accounting

Core tasks:

- runtime health report
- version drift visibility
- cost budget overrun
- benchmark regression gate
- broken transport diagnosis
- false success accounting

Metrics:

- accepted pass/fail
- diagnosis correctness
- false success count
- cost-budget overrun detection
- regression gate outcome
- runtime

Artifacts:

- prompt text
- transcript
- health or doctor output
- before/after state when relevant
- acceptance judgment

Publish rule:

- completed artifacts may be cited as local runtime-health and false-success
  accounting evidence; cost discipline remains its own dimension, not an
  observability sub-item

## B12. True Hybrid Retrieval Shootout

Benchmark id: `true_hybrid_retrieval_shootout`

Goal:

- compare FTS, vector, and hybrid retrieval on source-hit recall
- keep retrieval recall, latency, fallback, and token/cost estimate evidence in
  one contract
- preserve embedding baseline governance without silently changing the default
  baseline

Core tasks:

- knowledge-update source-hit recall
- temporal source-hit recall
- multi-session release-boundary recall
- per-mode fallback and latency accounting

Metrics:

- `recall_at_1`
- `recall_at_5`
- `recall_at_10`
- `p50_ms`
- `p95_ms`
- `fallback_reason`
- `token_cost_estimate`
- `fixture_only`

Artifacts:

- dataset manifest with dataset, split, oracle, and public boundary
- query list with expected source ids
- one result JSON per mode or per query/mode row
- rendered retrieval recall readiness section

Publish rule:

- fixture-only rows may validate the runner contract, but may not be cited as
  public retrieval recall
- source-hit recall must not be described as end-to-end answer correctness
- true vector-hybrid latency still requires a non-fallback hybrid row

## Current Follow-Up Priority

All executable BENCH gaps are closed as of 2026-06-08. BENCH-008 adds a v3.8
fixture contract plus a bounded local smoke source-hit recall run; it does not
reopen the closed backlog and it does not prove answer correctness or broad
corpus quality.
The next work is not to claim more from the current artifacts, but to improve
signal where the current results are intentionally bounded:

1. Re-run `client_enabled_vs_disabled` until named token/cost counters show a
   positive saving delta before any saving claim.
2. Broaden true-hybrid latency beyond the local synthetic fixture only when a
   larger dataset/hardware run exists.
3. Add optional live long-run maintenance coverage before claiming production
   auto-maintenance precision/recall.
4. Broaden `true_hybrid_retrieval_shootout` beyond local smoke source-hit recall
   before any broad retrieval-quality claim.
5. Keep `client_trace_evidence`, `maintenance_recovery`, and
   `retrieval_diagnostics` as maintainer-facing expansion suites.
