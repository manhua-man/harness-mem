# Benchmark Suite

Standalone benchmark workspace for `harness-mem`.

This directory is intentionally isolated from the main runtime, main docs, and
main pytest surfaces:

- it does not live under `docs/benchmark/`
- it does not live under `tests/`
- it does not change main `pytest.ini`
- its helper scripts use only the Python standard library

Use this directory for new benchmark design, execution notes, result bundles,
and publishable report assembly without pushing more benchmark mechanics into
the product path.

## Layout

```text
benchmark-suite/
  README.md
  BENCHMARKS.md
  GAPS.md
  RESULTS.md
  release-snapshot.json
  RUNBOOK.md
  suite.json
  retrieval_quality_longmemeval/
    prompts.json
    acceptance_checklist.md
  retrieval_diagnostics/
    prompts.json
    acceptance_checklist.md
  latency_warm_path/
    prompts.json
    acceptance_checklist.md
    driver.py
    result.schema.json
  client_enabled_vs_disabled/
    prompts.json
    acceptance_checklist.md
  memory_shortcut_vs_source_recovery/
    README.md
    prompts.json
    acceptance_checklist.md
  functional_token_economics/
    README.md
    prompts.json
    scenarios.json
    acceptance_checklist.md
    driver.py
  client_trace_evidence/
    prompts.json
    acceptance_checklist.md
  maintenance_recovery/
    prompts.json
    acceptance_checklist.md
  evidence_safety/
    prompts.json
    acceptance_checklist.md
  temporal_product_query/
    prompts.json
    acceptance_checklist.md
  generated_knowledge_freshness/
    prompts.json
    acceptance_checklist.md
  auto_maintenance_effectiveness/
    prompts.json
    acceptance_checklist.md
  runtime_health_observability/
    prompts.json
    acceptance_checklist.md
  true_hybrid_retrieval_shootout/
    README.md
    prompts.json
    acceptance_checklist.md
    dataset.manifest.json
    queries.json
  storage_v2_baseline/
    README.md
    prompts.json
    acceptance_checklist.md
    driver.py
  migration_roundtrip/
    README.md
    prompts.json
    acceptance_checklist.md
    driver.py
  local_index_fabric_smoke/
    README.md
    prompts.json
    acceptance_checklist.md
    driver.py
  templates/
    run_manifest.template.json
    task_result.template.json
    report.template.md
  tools/
    init_run.py
    validate_run.py
    render_report.py
  artifacts/
    .gitkeep
    .gitignore
```

## What belongs here

- benchmark catalog and rules
- execution runbooks
- prompt packs and acceptance criteria
- generated benchmark bundles under `artifacts/`
- accepted-run summary under `release-snapshot.json` when raw artifacts are not
  checked in
- helper scripts for bundle creation and report rendering

## What does not belong here

- product runtime code
- main regression tests
- user-facing README claims without completed evidence
- ad hoc scratch notes outside a benchmark run bundle

## Primary benchmark collections

See [BENCHMARKS.md](./BENCHMARKS.md) for the detailed collection set.
`memory_shortcut_vs_source_recovery` is the follow-up design pack for proving
bounded memory-shortcut token/source-reading savings; it complements, rather
than replaces, `client_enabled_vs_disabled`. `functional_token_economics` is a
separate fixture benchmark for feature-level progressive-disclosure token
economics; it is not a global token/cost saving benchmark.
v4.0.0 adds `storage_v2_baseline`, `migration_roundtrip`, and
`local_index_fabric_smoke` as diagnostic Storage v2 contract collections. They
establish corpus, migration, rollback, and manifest-last sidecar evidence
shape; they do not prove public Storage v2 performance gains.

## Current benchmark results

See [RESULTS.md](./RESULTS.md) for the artifact-backed metric summary. It
reports task counts, runtime deltas, latency percentiles, false-success counts,
and bounded publishable claims. `release-snapshot.json` is the tracked,
privacy-preserving summary consumed by `benchmark_matrix_report` when raw
artifact bundles are absent from a clean checkout.

The current matrix separates artifact acceptance from public-claim readiness:

| Gate | Current value | Meaning |
|---|---:|---|
| `gate.passed` | `true` | The eleven accepted BENCH bundles are internally valid. |
| `claim_readiness.token_cost_saving.ready` | `false` | The token-observed paired run had a negative saving delta; do not publish token/cost saving claims. |
| `claim_readiness.true_vector_hybrid_latency.ready` | `true` | A local synthetic true-hybrid probe ran without fallback; keep the claim scoped to that fixture. |
| `claim_readiness.retrieval_recall.ready` | `true` | A local smoke source-hit recall shootout ran across FTS/vector/hybrid; do not present it as answer correctness or broad corpus quality. |

This distinction matters for reference comparisons: `codedb-mcp` has a stronger
code-intel token/runtime benchmark, while this suite currently supports bounded
local `harness-mem` latency, source-hit recall, and feature-level token
economics claims.
Feature-level fixture token-economics claims must come from
`functional_token_economics` and stay scoped to estimated context payloads.

## Open benchmark gaps

See [GAPS.md](./GAPS.md) for the extracted issue backlog that tracks which
coverage dimensions are only smoke, methodology, tests, or planning today.

## Quick start

Create a new run skeleton:

```bash
python benchmark-suite/tools/init_run.py ^
  --benchmark-id client_enabled_vs_disabled ^
  --run-name codex-pass-01 ^
  --client codex ^
  --model gpt-5 ^
  --workspace F:\\memory-lab\\harness-mem
```

Validate a run bundle:

```bash
python benchmark-suite/tools/validate_run.py ^
  --run-dir benchmark-suite/artifacts/2026-06-06-client_enabled_vs_disabled-codex-pass-01
```

Validate the tracked clean-checkout summary:

```bash
python benchmark-suite/tools/check_release_artifacts.py

python benchmark-suite/tools/build_release_snapshot.py ^
  --output benchmark-suite/release-snapshot.json ^
  --check

python benchmark-suite/tools/validate_release_snapshot.py ^
  --path benchmark-suite/release-snapshot.json
```

Render `summary.csv` and `report.md` from task result JSON files:

For `client_enabled_vs_disabled`, result JSON files carry both the legacy
`token_total` field and a structured `token_usage` envelope. If the client does
not expose usage, keep `token_usage.available=false` and
`token_total="unavailable"`; do not treat missing usage as zero. When a client
does expose usage, provide sidecars to the runner with `--token-usage-dir` so
the report can compute `disabled - enabled` token deltas from named evidence.
Schema v2 result validation requires the envelope and rejects
`available=true` records that contain no numeric token/cost field.
When token data lives in a Codex JSONL session, use
`benchmark-suite/tools/extract_codex_token_usage.py` to export only numeric
`token_count` fields into a sidecar, then
`benchmark-suite/tools/apply_token_usage_sidecars.py` to write those sidecars
back into `results/*.json` before rendering the report.

```bash
python benchmark-suite/tools/render_report.py ^
  --run-dir benchmark-suite/artifacts/2026-06-06-client_enabled_vs_disabled-codex-pass-01
```

Run the isolated warm-path latency driver:

```bash
python benchmark-suite/latency_warm_path/driver.py ^
  --run-name local-pass-01 ^
  --workspace F:\\memory-lab\\harness-mem ^
  --samples 20 ^
  --warmup 5
```

Run the deterministic functional token-economics fixture:

```bash
python benchmark-suite/functional_token_economics/driver.py ^
  --run-name local-01 ^
  --workspace F:\\memory-lab\\harness-mem

python benchmark-suite/tools/render_report.py ^
  --run-dir benchmark-suite/artifacts/<run-dir>

python benchmark-suite/tools/validate_run.py ^
  --run-dir benchmark-suite/artifacts/<run-dir>
```

Run the v4.0.0 Storage v2 contract smokes:

```bash
python benchmark-suite/storage_v2_baseline/driver.py ^
  --run-name storage-v2-baseline-smoke

python benchmark-suite/migration_roundtrip/driver.py ^
  --run-name migration-roundtrip-smoke

python benchmark-suite/local_index_fabric_smoke/driver.py ^
  --run-name local-index-fabric-smoke
```

v4.0.1-v4.1 add contract/eval packs for
`canonical_store_runtime_baseline`, `rust_core_hot_path`,
`index_fabric_runtime_conformance`, `context_sufficiency_gate`, and
`task_aware_wake_precision`. These packs validate implementation contracts and
task-aware context behavior; they do not by themselves authorize public Storage
v2 speedup, native Rust performance, answer quality, or token/cost saving
claims.

## Policy

New benchmark work should be added here first. Only proven, durable benchmark
surfaces should later graduate into the main repo docs.
