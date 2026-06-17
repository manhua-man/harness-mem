# Runbook

This runbook is for maintainers running benchmark bundles from the standalone
suite.

## Rules

1. Do not run a benchmark against a moving target without writing down the repo
   state first.
2. Do not publish a claim that is not backed by an artifact bundle under
   `benchmark-suite/artifacts/`.
3. Do not mix benchmark conditions inside one run directory.
4. Do not estimate tokens if the client does not expose them; store
   `"unavailable"` instead.
5. Use `GAPS.md` as the executable backlog when deciding which missing
   benchmark to run or design next.
6. Keep feature-level fixture token-economics separate from global token/cost
   saving claims.

## Standard workflow

### 1. Create a run skeleton

```bash
python benchmark-suite/tools/init_run.py ^
  --benchmark-id client_enabled_vs_disabled ^
  --run-name codex-pass-01 ^
  --client codex ^
  --model gpt-5 ^
  --workspace F:\\memory-lab\\harness-mem
```

### 2. Fill in the run bundle

Put evidence into the generated run directory:

- `run_manifest.json`
- `report.md`
- `results/*.json`
- `transcripts/*`
- `notes/*`

### 3. Validate the bundle

```bash
python benchmark-suite/tools/validate_run.py ^
  --run-dir <run-dir>
```

### 4. Render the summary files

```bash
python benchmark-suite/tools/render_report.py ^
  --run-dir <run-dir>
```

### 5. Validate the release snapshot

When updating `benchmark-suite/release-snapshot.json`, validate the tracked
clean-checkout summary too:

```bash
python benchmark-suite/tools/check_release_artifacts.py
```

For lower-level diagnosis, rebuild and validate the snapshot directly:

```bash
python benchmark-suite/tools/build_release_snapshot.py ^
  --output benchmark-suite/release-snapshot.json ^
  --sync-package-resources

python benchmark-suite/tools/validate_release_snapshot.py ^
  --path benchmark-suite/release-snapshot.json
```

## Per-collection guidance

Before starting a new collection, check `benchmark-suite/GAPS.md` and confirm
whether the target gap is `ready-to-run`, `open`, or `blocked-by-product`.

## `retrieval_quality_longmemeval`

Use when:

- changing search ranking
- changing embeddings
- changing hybrid fusion logic

Minimum bundle:

- exact command
- exact dataset path
- result JSON
- one short markdown summary

Prompt and acceptance source:

- `benchmark-suite/retrieval_quality_longmemeval/prompts.json`
- `benchmark-suite/retrieval_quality_longmemeval/acceptance_checklist.md`

## `retrieval_diagnostics`

Use when:

- a retrieval-quality delta needs root-cause diagnosis
- aggregate scores are too weak to explain what changed
- temporal, fallback, fusion, or ranking behavior needs per-query evidence

Prompt and acceptance source:

- `benchmark-suite/retrieval_diagnostics/prompts.json`
- `benchmark-suite/retrieval_diagnostics/acceptance_checklist.md`

Minimum bundle:

- baseline and candidate identifiers
- representative query/ranking evidence
- notes for changed decisions or malformed scenarios

## `true_hybrid_retrieval_shootout`

Use when:

- comparing FTS, vector, and hybrid retrieval source-hit recall
- checking embedding baseline/candidate governance
- deciding whether retrieval recall or true hybrid latency claims are public
  claim ready

Prompt and acceptance source:

- `benchmark-suite/true_hybrid_retrieval_shootout/prompts.json`
- `benchmark-suite/true_hybrid_retrieval_shootout/acceptance_checklist.md`

Minimum bundle:

- `dataset.manifest.json` with dataset, split, oracle, and public boundary
- `queries.json` with expected source ids
- one result row per claimed mode
- rendered `Retrieval Recall Claim Readiness` section

Fixture rows may validate the v3.8 contract, but public retrieval recall claims
require `fixture_only=false` accepted rows for every claimed mode. True
vector-hybrid latency still requires an actual hybrid row with no fallback.

## `latency_warm_path`

Use when:

- changing wake renderer
- changing search path
- changing persistent vector behavior

Run:

```bash
python benchmark-suite/latency_warm_path/driver.py ^
  --run-name local-pass-01 ^
  --workspace F:\\memory-lab\\harness-mem ^
  --samples 20 ^
  --warmup 5
```

Minimum bundle:

- corpus size
- warm-up note
- p50/p95/max results
- rendered `Vector Hybrid Claim Readiness` section

Prompt and acceptance source:

- `benchmark-suite/latency_warm_path/prompts.json`
- `benchmark-suite/latency_warm_path/acceptance_checklist.md`

Only claim true vector-hybrid latency when the rendered report says
`True vector-hybrid claim ready: yes`. If `search_hybrid` falls back to FTS,
publish only the bounded synthetic warm-path result and preserve the
`effective_mode` / `fallback_reason` fields in any summary.

## `client_enabled_vs_disabled`

Use when:

- evaluating whether memory helps real continuation tasks

Required task design rules:

- pair each task with enabled and disabled conditions
- declare acceptance before running
- keep client/model/workspace fixed across the pair

Prompt and acceptance source:

- `benchmark-suite/client_enabled_vs_disabled/prompts.json`
- `benchmark-suite/client_enabled_vs_disabled/acceptance_checklist.md`

Minimum bundle:

- one `task_result` JSON per task/condition
- transcripts for every task/condition
- acceptance notes

Token-visible rerun flow:

1. Run paired tasks with fixed client, model, workspace, prompt text, and repo
   state.
2. Extract numeric token usage from client logs when available:

   ```bash
   python benchmark-suite/tools/extract_codex_token_usage.py ^
     --input C:\\path\\to\\codex-session.jsonl ^
     --output <run-dir>\\notes\\T1-enabled-token-usage.json
   ```

3. Apply sidecars to the run:

   ```bash
   python benchmark-suite/tools/apply_token_usage_sidecars.py ^
     --run-dir <run-dir>
   ```

4. Render and validate:

   ```bash
   python benchmark-suite/tools/render_report.py --run-dir <run-dir>
   python benchmark-suite/tools/validate_run.py --run-dir <run-dir>
   ```

Only claim token/cost deltas when every enabled and disabled result in the
claimed pair set has `token_usage.available=true` from a named source. Missing
token data remains `unavailable`; it is never treated as zero. The rendered
report includes a `Token Claim Readiness` section; do not publish token-saving
claims when it says `Token-saving claim ready: no`.

## `memory_shortcut_vs_source_recovery`

Use when:

- testing whether memory acts as a real shortcut on long-source recovery tasks
- investigating a positive token/source-reading saving claim after
  `client_enabled_vs_disabled` produced a neutral or negative broad-continuation
  result

Do not use when:

- the task is a tiny current-file lookup
- memory tools are unavailable in the client environment
- the source corpus is too small for disabled mode to incur real recovery cost

Prompt and acceptance source:

- `benchmark-suite/memory_shortcut_vs_source_recovery/prompts.json`
- `benchmark-suite/memory_shortcut_vs_source_recovery/acceptance_checklist.md`

Required task design rules:

1. Prepare an accepted memory packet before the run. It must summarize prior
   decisions but preserve source pointers.
2. Keep enabled and disabled prompt text identical except for the condition
   instruction.
3. Enabled mode must call memory first, then verify with minimal source reads.
4. Disabled mode must not call harness-mem read or write surfaces.
5. Both modes must cite source evidence; memory prose alone is not authority.
6. Record `source_read_count`, `cited_sources`, `memory_calls`, token usage, and
   runtime for every result.

Minimum bundle:

- one result JSON per task/condition
- transcripts for every task/condition
- notes describing the source corpus and memory packet seed
- rendered report with token delta and source-read delta tables

Positive-claim threshold:

- at least `6` of `8` long-source pairs pass in both conditions
- at least `6` passed long-source pairs stay within the enabled
  source-verification budget
- budget-ok median `disabled - enabled` total-token delta is at least `20%`
  positive
- at least `6` budget-ok passed long-source pairs reduce source reads in enabled
  mode
- negative controls stay within budget and do not show a meaningful memory
  advantage
- every token total comes from a named source

The rendered report also includes a cache-adjusted local token proxy:
`max(input - cached_input, 0) + output + reasoning`. Use it to diagnose Codex
cache pollution or execution-order artifacts. Do not use this proxy by itself to
flip `claim_readiness.token_cost_saving.ready=true`; public saving claims still
need the total-token/cost gate above, and real billing remains out of scope
without a separate telemetry benchmark.

If these thresholds fail, keep the run as diagnostic evidence. Do not fold the
result into `claim_readiness.token_cost_saving.ready=true`.

## `functional_token_economics`

Use when:

- preparing bounded claude-mem-style wording for progressive-disclosure token
  economics
- comparing compact wake/search/file-context/wiki payloads against declared
  source-reading baselines
- checking whether a feature-level token claim has deterministic fixture
  evidence

Do not use when:

- claiming global `harness-mem` token/cost savings
- claiming real billing savings
- benchmarking code-intelligence performance against `codedb-mcp` or Smart
  Explore
- proving that live agents always choose the compact path

Prompt and acceptance source:

- `benchmark-suite/functional_token_economics/prompts.json`
- `benchmark-suite/functional_token_economics/scenarios.json`
- `benchmark-suite/functional_token_economics/acceptance_checklist.md`

Run:

```bash
python benchmark-suite/functional_token_economics/driver.py ^
  --run-name local-01 ^
  --workspace F:\\memory-lab\\harness-mem
python benchmark-suite/tools/render_report.py --run-dir <run-dir>
python benchmark-suite/tools/validate_run.py --run-dir <run-dir>
```

Minimum bundle:

- `run_manifest.json`
- `notes/scenarios.json`
- one result JSON per scenario
- `summary.csv`
- rendered report with `Feature-Level Claim Readiness`
- rendered `Global Claim Boundary` that says global token/cost saving is not
  ready

Public wording is allowed only at the feature/fixture level, for example:
"compact progressive-disclosure payloads reduced estimated context tokens by
X% in the functional token-economics fixture benchmark." Do not fold this into
`claim_readiness.token_cost_saving.ready=true`.

## `client_trace_evidence`

Use when:

- proving user-visible runtime behavior in a real client

Minimum bundle:

- transcript
- tool call record if visible
- final user-visible output

Prompt and acceptance source:

- `benchmark-suite/client_trace_evidence/prompts.json`
- `benchmark-suite/client_trace_evidence/acceptance_checklist.md`

## `maintenance_recovery`

Use when:

- checking local maintenance-console diagnosis and recovery
- validating doctor/health guidance for broken state
- verifying recovery does not report false success

Prompt and acceptance source:

- `benchmark-suite/maintenance_recovery/prompts.json`
- `benchmark-suite/maintenance_recovery/acceptance_checklist.md`

Minimum bundle:

- input broken/stale state
- command or tool transcript
- before/after state when recovery is claimed
- recovery notes

## `evidence_safety`

Use when:

- checking whether the agent overclaims weak, generated, missing-source, or
  historical evidence

Prompt and acceptance source:

- `benchmark-suite/evidence_safety/prompts.json`
- `benchmark-suite/evidence_safety/acceptance_checklist.md`

Minimum bundle:

- one result JSON per task
- transcript for every task
- evidence notes for overclaim / abstention decisions

## `temporal_product_query`

Use when:

- checking product-level current/history/as_of/supersede behavior

Prompt and acceptance source:

- `benchmark-suite/temporal_product_query/prompts.json`
- `benchmark-suite/temporal_product_query/acceptance_checklist.md`

Minimum bundle:

- one result JSON per task
- transcript for every task
- source-backed temporal evidence notes

## `generated_knowledge_freshness`

Use when:

- v3.2 generated knowledge surfaces are stable and need freshness/source-map
  benchmarking

Do not run until the README unlock conditions are satisfied.

Prompt and acceptance source:

- `benchmark-suite/generated_knowledge_freshness/prompts.json`
- `benchmark-suite/generated_knowledge_freshness/acceptance_checklist.md`

## `auto_maintenance_effectiveness`

Use when:

- v3.1 opt-in maintenance surfaces are stable and need effectiveness,
  false-positive, undo, and ledger benchmarking

Do not run until the README unlock conditions are satisfied.

Prompt and acceptance source:

- `benchmark-suite/auto_maintenance_effectiveness/prompts.json`
- `benchmark-suite/auto_maintenance_effectiveness/acceptance_checklist.md`

## `runtime_health_observability`

Use when:

- v3.4 runtime health, cost, drift, regression, and false-success surfaces are
  stable

Do not run until the README unlock conditions are satisfied.

Prompt and acceptance source:

- `benchmark-suite/runtime_health_observability/prompts.json`
- `benchmark-suite/runtime_health_observability/acceptance_checklist.md`

## `storage_v2_baseline`

Use when:

- establishing the v4.0.0 deterministic Storage v2 corpus and baseline artifact
  schema
- running 10k / 100k / 1M profile evidence before any Storage v2 performance
  claim

Run:

```bash
python benchmark-suite/storage_v2_baseline/driver.py ^
  --run-name storage-v2-baseline-smoke

python benchmark-suite/storage_v2_baseline/driver.py ^
  --run-name storage-v2-baseline-10k ^
  --profile 10k
```

Validate:

```bash
python benchmark-suite/tools/validate_run.py --run-dir <run-dir>
```

## `migration_roundtrip`

Use when:

- proving dry-run, explicit side-by-side canonical apply, and rollback export
  checksums match
- validating that v4.0.0 migration evidence does not switch the default runtime
  backend

Run:

```bash
python benchmark-suite/migration_roundtrip/driver.py ^
  --run-name migration-roundtrip-smoke
```

Acceptance source:

- `benchmark-suite/migration_roundtrip/acceptance_checklist.md`

## `local_index_fabric_smoke`

Use when:

- checking the manifest-last sidecar evidence shape for Local Memory Index Fabric
- proving interrupted generations are not active before a manifest commit

Run:

```bash
python benchmark-suite/local_index_fabric_smoke/driver.py ^
  --run-name local-index-fabric-smoke
```

## `memory_eval_matrix`

Use when:

- checking the v4.2 memory-runtime behavior matrix
- adding or changing task-aware wake, sufficiency, candidate-noise, or
  multi-client compatibility gates

Prompt and acceptance source:

- `benchmark-suite/memory_eval_matrix/prompts.json`
- `benchmark-suite/memory_eval_matrix/acceptance_checklist.md`

Minimum bundle:

- one accepted result row per declared memory eval dimension
- source ids for evidence-backed rows
- claim boundary saying this is not a global answer-quality benchmark

## `retrieval_quality_pack`

Use when:

- changing reranker, query rewriting, multi-query/HyDE, embedding shootout, or
  retrieval drift behavior
- deciding whether any retrieval-quality component can move from optional or
  experimental to default

Prompt and acceptance source:

- `benchmark-suite/retrieval_quality_pack/prompts.json`
- `benchmark-suite/retrieval_quality_pack/acceptance_checklist.md`

Minimum bundle:

- one accepted result row per retrieval-quality capability
- recall/precision, false-positive, fanout, duplicate, latency, size, and
  install-friction fields where applicable
- claim boundary preserving default light-path behavior

## `code_memory_federation`

Use when:

- changing `file_context` code evidence, fingerprint, symbol, or project-root
  resolution behavior
- checking that generated code/wiki/module atlas layers do not become canonical
  truth

Prompt and acceptance source:

- `benchmark-suite/code_memory_federation/prompts.json`
- `benchmark-suite/code_memory_federation/acceptance_checklist.md`

Minimum bundle:

- code evidence rows with file path, source id, fingerprint, and line range
- stale-check status for current, stale, missing, and out-of-bounds cases
- claim boundary saying this is not a code-intel token/runtime benchmark

Boundary:

- this is code-evidence federation contract only; it is not a code-intel
  token/runtime benchmark and generated code/wiki/module atlas prose remains
  outside canonical truth.

## `claim_promotion_pack`

Use when:

- adding a public claim class
- changing `benchmark_matrix_report()["claim_readiness"]`
- editing README/CHANGELOG/benchmark wording that could promote a bounded or
  blocked claim

Prompt and acceptance source:

- `benchmark-suite/claim_promotion_pack/prompts.json`
- `benchmark-suite/claim_promotion_pack/acceptance_checklist.md`

Minimum bundle:

- one accepted result row per declared claim policy
- `promotion_status`, `claim_ready`, `public_claim_allowed`, and
  `blocked_reason` fields for every row
- report text that keeps token/cost saving, Storage v2 speedup, default
  reranker/HyDE, and code-memory token/runtime claims blocked unless their
  specific upstream gate changes

## `release_evidence_pack`

Use when:

- rebuilding `benchmark-suite/release-snapshot.json`
- syncing `harness_mem/resources/benchmark_suite/*`
- checking clean-checkout behavior after adding or removing benchmark
  collections/artifacts

Prompt and acceptance source:

- `benchmark-suite/release_evidence_pack/prompts.json`
- `benchmark-suite/release_evidence_pack/acceptance_checklist.md`

Minimum bundle:

- one accepted release-evidence result row
- `snapshot_run_count`, `accepted_runs`, `failed_runs`, `unknown_runs`,
  `packaged_resource_match`, and `claim_promotion_policy_enforced`
- report text saying the pack does not upgrade blocked public claims

## `context_outcome_loop`

Use when:

- changing `record_context_outcome`
- changing context outcome signal storage or scoring
- changing opt-in search/wake ranking explanation metadata

Prompt and acceptance source:

- `benchmark-suite/context_outcome_loop/prompts.json`
- `benchmark-suite/context_outcome_loop/acceptance_checklist.md`

Run:

```bash
python -m pytest tests/loop_harness/test_context_outcome_loop.py -q --capture=no
```

Minimum evidence:

- loop harness stdout with `[loop_harness:context_outcome_loop]`
- `context_outcome_signals`, `used_score_positive`,
  `misleading_score_negative`, `explained_result_count`, and
  `truth_mutation_count`
- claim boundary saying outcome feedback is signal-only, opt-in, and not a
  broad answer-quality or token/cost saving claim

## `canonical_store_runtime_baseline`

Use when validating v4.0.1 canonical entity tables, metadata filters,
compatibility reader, snapshot export, dual-write gate, and Storage v2 doctor
health. Acceptance source:
`benchmark-suite/canonical_store_runtime_baseline/acceptance_checklist.md`.

## `rust_core_hot_path`

Use when validating the v4.0.2 Rust-core facade, fallback reporting, tolerant
JSONL scanner, ranking primitives, and local crate shape. Acceptance source:
`benchmark-suite/rust_core_hot_path/acceptance_checklist.md`.

## `index_fabric_runtime_conformance`

Use when validating v4.0.3 SearchBackend conformance, manifest-last sidecars,
interrupted-generation invisibility, lazy rebuild, and source fingerprint drift.
Acceptance source:
`benchmark-suite/index_fabric_runtime_conformance/acceptance_checklist.md`.

## `context_sufficiency_gate`

Use when evaluating v4.1 deterministic sufficiency checks and bounded
iterative retrieval. Acceptance source:
`benchmark-suite/context_sufficiency_gate/acceptance_checklist.md`.

## `task_aware_wake_precision`

Use when evaluating v4.1 task-aware wake packet budget traces, include/omit
reasons, and fixture precision. Acceptance source:
`benchmark-suite/task_aware_wake_precision/acceptance_checklist.md`.

## Result quality checklist

Before accepting a bundle, verify:

- repo state recorded
- benchmark id matches the actual work
- timestamps present
- transcripts present where required
- report can be understood without chat context

## Graduation rule

A benchmark only moves into main docs when:

1. the method is stable
2. the artifact bundle is complete
3. the result is not contradicted by current repo truth
4. the wording can be made user-facing without caveats swallowing the claim
