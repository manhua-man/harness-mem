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
| Memory runtime | `retrieval_quality_longmemeval`, `retrieval_diagnostics`, `client_enabled_vs_disabled` | Retrieval quality has durable historical coverage; client value is methodology / smoke only until paired runs exist. | Finish `client_enabled_vs_disabled` paired runs before claiming user-visible memory value. |
| Evidence safety | `evidence_safety`, `client_trace_evidence` | Design is ready to run; current repo evidence is mostly tests and packet transcripts until artifact bundles exist. | Run the evidence-safety pack before claiming agents avoid evidence overclaiming. |
| Generated knowledge | `generated_knowledge_freshness` | Design pack exists but is blocked by v3.2 product surfaces; existing checks are anti-contamination tests, not benchmark results. | Run only after source maps, freshness, atomic claims, and generated context surfaces are stable. |
| Temporal query | `temporal_product_query`, `retrieval_quality_longmemeval`, `retrieval_diagnostics` | Product-query design is ready to run; LongMemEval already covers temporal-reasoning retrieval. | Run the product temporal pack before claiming `current` / `history` / `as_of` / supersede explainability beyond retrieval quality. |
| Auto maintenance | `auto_maintenance_effectiveness`, `maintenance_recovery` | v3.1 `/hm:dream` ledger/apply/reject/undo surfaces exist; no completed effectiveness artifact yet. | Run `auto_maintenance_effectiveness` before claiming automatic maintenance quality. |
| Observability | `runtime_health_observability`, `maintenance_recovery`, `client_trace_evidence` | Design pack exists but is blocked by v3.4 runtime-health/cost/regression surfaces. | Run after runtime health report, local cost observer, drift visibility, and regression gates ship. |
| Cost discipline | `client_enabled_vs_disabled` | Methodology and smoke exist; no completed enabled-vs-disabled token/runtime result yet. | This is the first benchmark to complete before public token, cost, or time-savings claims. |
| Performance | `latency_warm_path`, `retrieval_quality_longmemeval` | Historical v1.5/v1.6 docs cover synthetic latency and per-question runtime; current suite has warm-path smoke only. | Run a non-smoke warm-path pass with enough samples and explicit fallback notes. |

Coverage levels:

- **Result**: completed run artifacts exist and can support a bounded claim.
- **Smoke**: scaffold or driver proved shape only; do not cite as a product
  result.
- **Methodology**: benchmark design exists, but no completed paired result.
- **Test / planning only**: regression tests or roadmap docs exist, but no
  benchmark claim is supported.

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
- token total if visible
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

- blocked until v3.2 generated knowledge surfaces ship; generated prose must
  never be reported as confirmed truth

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

- blocked until v3.4 runtime health/cost/regression surfaces ship; cost
  discipline remains its own dimension, not an observability sub-item

## Recommended initial priority

Run these first:

1. `client_enabled_vs_disabled`
2. `evidence_safety`
3. `temporal_product_query`
4. `latency_warm_path`
5. `retrieval_quality_longmemeval`

Run after product surfaces stabilize:

1. `generated_knowledge_freshness`
2. `auto_maintenance_effectiveness`
3. `runtime_health_observability`

Defer these until the first five are stable:

1. `client_trace_evidence`
2. `maintenance_recovery`
3. `retrieval_diagnostics`
