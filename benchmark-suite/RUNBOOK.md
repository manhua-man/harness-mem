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
