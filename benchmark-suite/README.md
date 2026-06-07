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
- helper scripts for bundle creation and report rendering

## What does not belong here

- product runtime code
- main regression tests
- user-facing README claims without completed evidence
- ad hoc scratch notes outside a benchmark run bundle

## Primary benchmark collections

See [BENCHMARKS.md](./BENCHMARKS.md) for the detailed collection set.

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

Render `summary.csv` and `report.md` from task result JSON files:

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

## Policy

New benchmark work should be added here first. Only proven, durable benchmark
surfaces should later graduate into the main repo docs.
