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
| Memory runtime | `retrieval_quality_longmemeval`, `retrieval_diagnostics`, `client_enabled_vs_disabled`, `memory_shortcut_vs_source_recovery` | `client_enabled_vs_disabled` has completed paired artifacts; the token-visible run proves task correctness and memory-call gating, but T1/T3 have negative saving deltas. `memory_shortcut_vs_source_recovery` is the follow-up design pack for discriminative long-source memory-shortcut evidence. | Run the memory-shortcut suite before any positive token/source-reading saving claim. |
| Evidence safety | `evidence_safety`, `client_trace_evidence` | `evidence_safety` has a completed E1-E5 guarded artifact with overclaim and abstention pressure. | Expand only if a new evidence boundary is added; do not generalize beyond the exact task set. |
| Generated knowledge | `generated_knowledge_freshness` | v3.2 surfaces shipped and GK1-GK5 completed with source-map, freshness, generated-only, invalidation, and citation-laundering checks. | Keep generated prose out of confirmed truth; use future runs for claims-first/source-map coverage improvements. |
| Temporal query | `temporal_product_query`, `retrieval_quality_longmemeval`, `retrieval_diagnostics` | TQ1-TQ5 completed for current/history/as_of/supersede/ambiguity behavior; LongMemEval remains retrieval-quality evidence. | Use product temporal artifacts for product claims; use LongMemEval for retrieval claims. |
| Auto maintenance | `auto_maintenance_effectiveness`, `maintenance_recovery`, `guided_maintenance_profiles` | v3.1 `/hm:dream` surfaces shipped and AM1-AM6 completed for merge/stale/supersede/reject/undo/ledger behavior. v5.8 adds a deterministic profile dry-run smoke for guided opt-in maintenance without running dream/metabolism. | Do not claim production long-run precision/recall without a live maintenance benchmark; profile smoke proves UX/safety wiring only. |
| Observability | `runtime_health_observability`, `maintenance_recovery`, `client_trace_evidence` | v3.4.4 runtime health/cost/regression surfaces shipped and RH1-RH6 completed, including false-success accounting. | Cloud telemetry and real billing are out of scope unless a separate benchmark is added. |
| Cost discipline | `client_enabled_vs_disabled`, `memory_shortcut_vs_source_recovery`, `functional_token_economics`, `runtime_health_observability` | Cost surfaces and budget-overrun detection are covered; the 2026-06-09 token-observed pair has named token totals but a negative saving delta. `memory_shortcut_vs_source_recovery` also reports a cache-adjusted local token proxy for diagnosis, but that proxy is not a public cost claim gate. `functional_token_economics` is the separate feature-level fixture benchmark for claude-mem-style progressive-disclosure token claims. | Use `functional_token_economics` only for bounded fixture payload claims. No global token/cost saving claim until a paired long-source shortcut run reports a positive disabled-minus-enabled total-token/cost delta from a named source. |
| Performance | `latency_warm_path`, `true_hybrid_retrieval_shootout`, `retrieval_quality_longmemeval` | Non-smoke warm-path FTS/wake run completed; the 2026-06-09 true-hybrid probe ran with `effective_mode=hybrid` and no fallback. | Keep true-hybrid latency claims scoped to the local synthetic fixture unless a broader dataset/hardware run is added. |
| Retrieval recall | `true_hybrid_retrieval_shootout`, `retrieval_quality_longmemeval`, `retrieval_diagnostics` | v3.8 has fixture-contract rows plus a local smoke source-hit recall artifact across FTS/vector/hybrid. `claim_readiness.retrieval_recall.ready` is true for that bounded local split. | Do not present source-hit recall as end-to-end answer correctness or broad corpus quality. |
| Storage v2 / Index fabric | `storage_v2_baseline`, `migration_roundtrip`, `local_index_fabric_smoke` | v4.0.0 has diagnostic smoke artifacts for deterministic synthetic corpus generation, migration dry-run/apply/export checksums, and manifest-last sidecar contract shape. These are contract/schema evidence only. | Run 10k / 100k / 1M release artifacts before any Storage v2 speedup claim; v4.0.1+ must add runtime canonical-store/index-fabric evidence before changing defaults. |
| Memory eval matrix | `memory_eval_matrix`, `context_sufficiency_gate`, `task_aware_wake_precision` | v4.2 has an accepted contract artifact covering eight memory-runtime behavior dimensions. This is a release gate shape, not a global answer-quality benchmark. | Expand with real replay/eval rows before any broad memory-quality claim. |
| Outcome-aware context loop | `context_outcome_loop` | v5.5 adds a deterministic loop-harness scenario for `record_context_outcome -> RetrievalSignal(context_outcome) -> opt-in SearchBackend ranking metadata`, with truth mutation count pinned at zero. | Keep this as a release safety gate; do not claim answer-quality improvement without replay/user-task artifacts. |
| Retrieval quality pack | `retrieval_quality_pack`, `true_hybrid_retrieval_shootout`, `retrieval_diagnostics` | v4.2 has an accepted contract artifact for reranker, query rewriting, multi-query/HyDE, embedding shootout, and retrieval drift gates. Defaults remain conservative. | Do not enable reranker/HyDE or change the embedding baseline without component artifacts that pass recall, latency, disk/cache, and install-friction gates. |
| Code-memory federation | `code_memory_federation` | v4.3 has an accepted contract artifact for file fingerprints, symbols, stale code-evidence checks, and generated-layer truth boundary. | Do not translate this into code-intel token/runtime savings or treat generated module atlas/wiki prose as truth. |
| Claim promotion governance | `claim_promotion_pack` | v4.4 has an accepted contract artifact that keeps blocked, bounded, and public-ready claim states machine-readable. | Do not convert governance coverage into token/cost saving, Storage v2 speedup, default reranker/HyDE, or code-intel runtime claims. |
| Release evidence packaging | `release_evidence_pack` | v4.5 has an accepted contract artifact for clean-checkout snapshot/package-resource consistency and claim-promotion visibility. | Do not treat evidence packaging as an upgrade to blocked claim readiness. |

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
- v4.0.x-v4.5 smoke and contract artifacts are included in the release snapshot
  as bounded contract evidence. They do not prove public performance gains,
  token/cost savings, default reranker/HyDE enablement, broad retrieval quality,
  or end-to-end answer correctness.

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

## B1b. Memory Eval Matrix

Benchmark id: `memory_eval_matrix`

Goal:

- keep the v4.2 memory-runtime behavior dimensions release-gated
- cover cross-session resume, stale truth rejection, raw evidence recovery,
  candidate noise rejection, task-aware wake precision, multi-client
  consistency, wire-format compatibility, and context sufficiency accuracy

Core tasks:

- one row per memory eval dimension
- source-backed safe-to-answer / false-positive checks

Metrics:

- dimension coverage
- retrieved source ids
- false-positive count
- safe-to-answer status

Artifacts:

- result JSON per dimension
- dataset manifest
- markdown report

Publish rule:

- may be cited as release-gate coverage only, not as broad answer-quality proof

## B1c. Context Outcome Loop

Benchmark id: `context_outcome_loop`

Goal:

- verify the v5.5 feedback loop from returned source id to outcome signal to
  explainable opt-in ranking metadata
- prove outcome feedback is a signal-only path, not a confirmed-truth mutation

Core tasks:

- MCP search returns source ids for a deterministic fixture
- `record_context_outcome` records `used` and `misleading` signals
- opt-in search returns `context_outcome_score` and
  `ranking_explanation(kind=context_outcome)`

Metrics:

- `context_outcome_signals`
- `used_score_positive`
- `misleading_score_negative`
- `explained_result_count`
- `truth_mutation_count`

Artifacts:

- `tests/loop_harness/test_context_outcome_loop.py`
- pytest stdout line `[loop_harness:context_outcome_loop] ...`
- loop harness README scenario entry

Publish rule:

- may be cited only as a release safety gate for explainable signal wiring
- must not be phrased as broad answer-quality, token/cost, or production
  ranking improvement evidence

## B1d. Retrieval Quality Pack

Benchmark id: `retrieval_quality_pack`

Goal:

- gate retrieval-quality components before changing defaults
- keep reranker, query rewriting, multi-query/HyDE, embedding shootout, and
  drift-suite behavior separately accountable

Core tasks:

- one row per retrieval-quality capability
- compare recall uplift, false-positive drift, fanout, duplicate rate,
  sufficiency delta, latency, size, and install friction where relevant

Metrics:

- precision / recall deltas
- false-positive delta
- fanout cost and duplicate rate
- model size and cold start

Artifacts:

- result JSON per capability
- dataset manifest
- markdown report

Publish rule:

- may be cited as component-gate coverage only; it does not enable reranker,
  HyDE, or embedding baseline changes by default

## B1e. Code-Memory Federation

Benchmark id: `code_memory_federation`

Goal:

- gate v4.3 file fingerprint, code symbol, and stale code-evidence behavior
- preserve the boundary that generated code/wiki/module-atlas prose is not
  canonical truth

Core tasks:

- current code evidence
- stale fingerprint evidence
- generated-layer truth-boundary evidence

Metrics:

- stale status
- line-range status
- current symbols present
- generated layer truth-boundary flag

Artifacts:

- result JSON per task
- dataset manifest
- markdown report

Publish rule:

- may be cited as code-evidence federation contract coverage only, not as
  code-intel token/runtime or answer-quality proof

## B1f. Claim Promotion Pack

Benchmark id: `claim_promotion_pack`

Goal:

- gate public-claim promotion with machine-readable policy
- keep blocked claims blocked even when neighboring bounded-local claims are
  ready
- prevent documentation/reporting drift around token/cost saving, Storage v2
  speedup, default reranker/HyDE, and code-memory token/runtime claims

Core tasks:

- one row per claim policy
- blocked / bounded / public-ready status checks
- evidence reference and promotion boundary checks

Metrics:

- `promotion_status`
- `claim_ready`
- `public_claim_allowed`
- `bounded_scope`
- `blocked_reason`

Artifacts:

- result JSON per claim
- dataset manifest
- markdown report

Publish rule:

- may be cited as claim-governance coverage only; it does not prove the
  underlying performance, token, default-behavior, or answer-quality claims

## B1g. Release Evidence Pack

Benchmark id: `release_evidence_pack`

Goal:

- gate clean-checkout release evidence packaging
- verify tracked release snapshot and packaged benchmark resources stay in sync
- ensure claim-promotion policy is visible to runtime consumers

Core tasks:

- release snapshot consistency
- packaged suite / snapshot resource sync
- accepted-run count and failed/unknown count checks
- no-overclaim boundary check

Metrics:

- `snapshot_run_count`
- `accepted_runs`
- `failed_runs`
- `unknown_runs`
- `packaged_resource_match`
- `claim_promotion_policy_enforced`

Artifacts:

- one release-evidence result JSON
- dataset manifest
- markdown report

Publish rule:

- may be cited as release-evidence packaging coverage only; it does not upgrade
  blocked claims or prove new performance/token-saving behavior

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
- its current token-visible result is diagnostic/anti-overclaim evidence, not a
  positive saving result

## B4a. Memory Shortcut vs Source Recovery

Benchmark id: `memory_shortcut_vs_source_recovery`

Goal:

- measure whether accepted memory packets reduce token and source-reading cost
  on long-source recovery tasks where disabled mode must recover truth from
  docs, archived packets, release snapshots, or benchmark artifacts

Why this exists:

- `client_enabled_vs_disabled` is intentionally broad and realistic; easy repo
  truth tasks can make disabled mode cheaper than enabled mode
- this suite creates discriminative tasks where memory and source-only recovery
  should follow different paths

Core tasks:

- release claim boundary recovery
- reference-project absorption boundary
- Auto Dream / maintenance boundary
- generated knowledge authority boundary
- temporal truth / supersede explanation
- runtime health vs cost discipline separation
- cross-client daily workflow boundary
- embedding baseline governance
- negative controls for tiny current CI and obvious repo facts

Metrics:

- token total and `token_usage` source
- cache-adjusted local token proxy when `input` / `cached_input` / `output` /
  `reasoning` counters are available
- runtime
- prompt turns and follow-up count
- `source_read_count`
- cited source paths
- memory call list
- accepted pass/fail
- disabled-minus-enabled token delta
- disabled-minus-enabled cache-adjusted token proxy delta
- disabled-minus-enabled source-read delta

Artifacts:

- prompt text
- transcripts for both conditions
- memory call and source-read records
- cited source list
- paired result JSON
- rendered token/source-read delta report

Publish rule:

- do not publish a positive memory-shortcut token/cost claim unless at least `6`
  of `8` long-source pairs pass in both conditions, at least `6` passed pairs
  stay within the enabled source-verification budget, the budget-ok median token
  delta from total tokens is at least `20%` positive, at least `6` budget-ok
  passed pairs reduce source reads, and negative controls stay within budget
  without showing a meaningful memory advantage
- even then, the claim is limited to long-source recovery tasks; it does not
  prove global or real-billing savings

Cost-claim evidence boundary:

- cost discipline is its own claim class, not an observability subcategory
- false-success accounting, budget overrun evidence, and truncation evidence are
  required before public token/cost claims
- diagnostic, partial, quarantined, or `release_snapshot=false` artifacts are
  excluded from release snapshots unless explicitly promoted
- cache-adjusted local token proxy is calculated as
  `max(input - cached_input, 0) + output + reasoning`; it helps diagnose cache
  pollution in Codex runs but does not unlock a public saving claim when total
  tokens or real billing evidence are negative or unavailable
- local token counters can support bounded local benchmark evidence, but they do
  not prove cloud telemetry or real billing savings

## B4b. Functional Token Economics

Benchmark id: `functional_token_economics`

Goal:

- measure feature-level fixture context-token economics for progressive
  disclosure workflows
- give maintainers a safe claude-mem-style claim shape without pretending that
  it proves whole-product token savings
- keep cost/performance claims separate from runtime observability

Core tasks:

- progressive recall compact packet versus broad source recovery
- file-context preflight versus reading the full target file
- compact wake versus broad status/session context
- wiki compact index versus direct multi-document reading

Metrics:

- `baseline_tokens`
- `optimized_tokens`
- `token_delta`
- `saving_ratio`
- `minimum_saving_ratio`
- tokenizer/source metadata
- `fixture_only`

Artifacts:

- `scenarios.json`
- one result JSON per scenario
- `summary.csv`
- rendered report with `Feature-Level Claim Readiness`
- global non-claim boundary

Publish rule:

- may support bounded wording such as "in the functional token-economics
  fixture benchmark, compact progressive-disclosure payloads reduced estimated
  context tokens by X%"
- must not be used as a global `harness-mem` token/cost saving claim
- must not be described as real billing savings, live-agent behavior, answer
  quality, or code-intelligence performance

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

## B10b. Guided Maintenance Profiles

Benchmark id: `guided_maintenance_profiles`

Goal:

- verify v5.8 guided maintenance profiles are explicit opt-in presets with
  explainable dry-run summaries
- prove profile status previews do not silently run dream/metabolism or mutate
  confirmed truth

Core tasks:

- set `ProjectProfile.maintenance_profile` through MCP profile update
- read `get_project_status` maintenance profile blocks
- verify dry-run summary fields and no-op behavior
- verify truth, candidate, and retrieval-signal counts stay unchanged

Metrics:

- `profile_update_success`
- `dry_run_count`
- `summary_fields_present`
- `auto_applied_count`
- `truth_mutation_count`
- `candidate_mutation_count`
- `signal_mutation_count`

Artifacts:

- `tests/loop_harness/test_guided_maintenance_profiles.py`
- pytest stdout line `[loop_harness:guided_maintenance_profiles] ...`
- loop harness README scenario entry

Publish rule:

- may be cited only as a release safety gate for guided profile dry-runs
- must not be phrased as production maintenance precision, answer-quality,
  token/cost, scheduler, or daemon-readiness evidence

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

## B13. Storage v2 Baseline

Benchmark id: `storage_v2_baseline`

Goal:

- establish deterministic v4.0 corpus generation before changing storage
- measure legacy JSON scan/baseline artifact fields with fixed seed, entry mix,
  payload size, and project count
- keep Storage v2 performance claims locked until larger release artifacts exist

Core tasks:

- generate 10k / 100k / 1M synthetic corpus profiles
- record dataset hash, command, hardware, commit, p50/p95, memory, disk, DB
  size, and fallback fields
- render claim readiness as diagnostic smoke unless promoted

Metrics:

- `entry_count`
- `json_file_count`
- `p50_ms`
- `p95_ms`
- `rss_peak_mb`
- `disk_bytes`
- `db_size_bytes`
- `claim_readiness`

Artifacts:

- `dataset.manifest.json`
- one result JSON per run
- `summary.csv`
- rendered report
- dry-run notes when available

Publish rule:

- diagnostic smoke rows do not support public speedup claims
- any Storage v2 performance wording requires 10k / 100k / 1M artifact-backed
  runs and explicit claim readiness

## B14. Migration Roundtrip

Benchmark id: `migration_roundtrip`

Goal:

- prove the v4.0.0 migration contract is reversible on a deterministic corpus
- verify dry-run checksum, side-by-side canonical SQLite apply, and rollback
  export back to v3-compatible JSON blobs

Core tasks:

- run Storage v2 dry-run without writing
- explicitly apply to `store_v2/canonical.sqlite`
- export rollback snapshot and compare logical checksums

Metrics:

- `dry_run_checksum`
- `canonical_checksum`
- `rollback_checksum`
- `apply_checksum_match`
- `rollback_checksum_match`
- `db_size_bytes`
- `p50_ms`
- `p95_ms`

Artifacts:

- dry-run plan JSON
- canonical DB size measurement
- rollback checksum result
- rendered roundtrip report

Publish rule:

- may support "migration contract is reversible on the measured corpus"
- must not be phrased as default canonical-store enablement or production
  migration performance

## B15. Local Index Fabric Smoke

Benchmark id: `local_index_fabric_smoke`

Goal:

- establish the manifest-last sidecar artifact shape for Local Memory Index
  Fabric without claiming runtime SearchBackend implementation
- verify interrupted generation sidecars do not become the active manifest

Core tasks:

- write an interrupted generation
- write an active generation and commit `manifest.json` last
- record source fingerprint drift detection and sidecar size

Metrics:

- `manifest_commit`
- `interrupted_generation_visible`
- `source_fingerprint_drift_detected`
- `sidecar_size_bytes`
- `fallback_reason`
- `claim_readiness`

Artifacts:

- `dataset.manifest.json`
- sidecar manifest note
- one result JSON
- rendered manifest-last report

Publish rule:

- may support "manifest-last sidecar contract smoke exists"
- must not be used as runtime index-fabric, Tantivy, LanceDB, or broad search
  performance evidence

## Evidence Hardening Track Status

Status as of 2026-06-16: completed as a bounded evidence pack. The current
release snapshot carries accepted runs for v4.6-v5.0 and
`default_change_decision_gate.ready=true`; this still does **not** upgrade the
public-claim boundaries below.

| Slice | Benchmark focus | Required evidence | Claim boundary |
|---|---|---|---|
| v4.6 Cost / Token Evidence | `memory_shortcut_vs_source_recovery` plus `functional_token_economics` | named token/cost sidecars, paired enabled/disabled rows, source_read_count, negative controls, bounded report | no global token/cost saving claim |
| v4.7 Storage v2 Scale Evidence | `storage_v2_baseline`, `migration_roundtrip`, `canonical_store_runtime_baseline` | 10k / 100k / 1M corpus, v3 JSON vs canonical SQLite, cold/warm path, RSS, disk, file count, rollback checksum | no default canonical store or Storage v2 speedup claim |
| v4.8 Index Fabric Runtime Evidence | `index_fabric_runtime_conformance`, `local_index_fabric_smoke` | exact/word/trigram/graph sidecar runtime rows, first lazy load vs warm path, fallback metadata, fingerprint drift/lazy rebuild | no Tantivy/LanceDB/ANN readiness claim |
| v4.9 Rust Native Hot Path Evidence | `rust_core_hot_path` | native vs Python fallback rows for JSONL scan, bulk index, RRF/ranking, tokenize, plus wheel/platform mode | no Rust speedup claim without native artifact |
| v5.0 Default Change Decision Gate | claim-gate rollup across the above | all relevant claim gates ready with artifact-backed evidence | no default storage/index/reranker/HyDE change from smoke alone |

This track borrows `codedb-mcp`'s index discipline, benchmark discipline, and
cost-observer discipline, but keeps `harness-mem` scoped to a local-first memory
runtime rather than a code-intel product.

## B16. Canonical Store Runtime Baseline

Benchmark id: `canonical_store_runtime_baseline`

Goal: validate v4.0.1 canonical entity tables, metadata filters, compatibility
reader, snapshot export, dual-write gate, and doctor health. Publish rule: this
is contract evidence only, not public Storage v2 speedup evidence.

## B17. Rust Core Hot Path

Benchmark id: `rust_core_hot_path`

Goal: validate the v4.0.2 Rust-core facade, tolerant JSONL scanner, ranking
primitives, error mapping, and explicit pure-Python fallback. Publish rule:
native Rust speed is not claimed unless a platform wheel artifact proves it.

## B18. Index Fabric Runtime Conformance

Benchmark id: `index_fabric_runtime_conformance`

Goal: validate SearchBackend conformance, manifest-last sidecar publication,
interrupted-generation invisibility, lazy rebuild, and source-fingerprint drift.
Publish rule: this is not Tantivy, LanceDB, or ANN readiness evidence.

## B19. Context Sufficiency Gate

Benchmark id: `context_sufficiency_gate`

Goal: evaluate v4.1 deterministic sufficiency checks: direct support, missing
evidence, conflicts, source diversity, safe-to-answer, and bounded iterative
retrieval. Publish rule: this is not LLM judge or end-to-end answer-quality
evidence.

## B20. Task-Aware Wake Precision

Benchmark id: `task_aware_wake_precision`

Goal: evaluate v4.1 wake packet budgeting, hard/soft include reasons,
why_omitted, precision-at-k fixture behavior, and default hot/warm tier
semantics. Publish rule: this is not a global token/cost saving claim.

All executable BENCH gaps are closed as of 2026-06-08. BENCH-008 adds a v3.8
fixture contract plus a bounded local smoke source-hit recall run; it does not
reopen the closed backlog and it does not prove answer correctness or broad
corpus quality. v4.0.0 adds Storage v2 diagnostic contract smokes; those remain
excluded from public performance claims until larger release artifacts exist.
v4.0.1-v4.5 add contract/eval packs for canonical store, Rust fallback, runtime
index fabric, context sufficiency, task-aware wake, memory eval, retrieval
quality, code-memory federation, claim promotion, and release evidence; those
packs are also artifact-bounded and do not create public speedup, token-saving,
default-behavior, code-intel runtime, or answer-quality claims.
The next work is not to claim more from the current artifacts, but to improve
signal where the current results are intentionally bounded:

No global token-saving claim until a paired run reports a positive disabled-minus-enabled token/cost delta from a named source.

1. Run `functional_token_economics` for bounded feature-level fixture wording
   around compact progressive-disclosure payloads.
2. Run `memory_shortcut_vs_source_recovery` with named token/cost counters before
   any positive memory-shortcut saving claim; keep `client_enabled_vs_disabled`
   as the broad anti-overclaim continuation gate.
3. Broaden true-hybrid latency beyond the local synthetic fixture only when a
   larger dataset/hardware run exists.
4. Add optional live long-run maintenance coverage before claiming production
   auto-maintenance precision/recall.
5. Broaden `true_hybrid_retrieval_shootout` beyond local smoke source-hit recall
   before any broad retrieval-quality claim.
6. Keep `client_trace_evidence`, `maintenance_recovery`, and
   `retrieval_diagnostics` as maintainer-facing expansion suites.
7. Run `storage_v2_baseline` and `migration_roundtrip` on 10k / 100k / 1M
   profiles before claiming Storage v2 migration or performance readiness.
