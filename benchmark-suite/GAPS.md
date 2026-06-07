# Benchmark Gap Backlog

This file extracts the current benchmark coverage gaps into executable issues.
It is intentionally stricter than the product roadmap: a roadmap item can be
planned, but a benchmark gap closes only when artifact-backed results exist.

## Status Legend

- `open`: no publishable benchmark result exists yet.
- `blocked-by-product`: the product surface is still planning-only or not stable
  enough to benchmark.
- `ready-to-run`: prompts, acceptance rules, and artifact schema are sufficient
  to start collecting results.
- `closed`: completed artifact bundle exists and the result is not contradicted
  by current repo truth.

## P0 Gaps

### GAP-BENCH-001: Client Continuation Value

Dimension:

- Memory runtime
- Cost discipline
- Performance

Current status: `ready-to-run`

Current evidence:

- Methodology: `docs/benchmark/agent-enabled-vs-disabled.md`
- Suite collection: `client_enabled_vs_disabled`
- Prompt pack: `benchmark-suite/client_enabled_vs_disabled/prompts.json`
- Acceptance checklist:
  `benchmark-suite/client_enabled_vs_disabled/acceptance_checklist.md`
- Existing artifact is smoke only:
  `benchmark-suite/artifacts/2026-06-06-client_enabled_vs_disabled-smoke/`

Why this remains open:

- The smoke bundle contains only `T1 enabled`.
- No disabled pair exists.
- No `3-5` paired task set exists.
- Token values are still `unavailable`, so no token-saving claim is supported.

Required work:

- Run at least `3` paired tasks and preferably `5`.
- Keep client, model, workspace, prompt, and repo state fixed across each pair.
- Record transcripts for both enabled and disabled conditions.
- Record `memory_calls` in enabled mode and prove it is empty in disabled mode.
- Record token totals only if exposed by the client; otherwise use
  `"unavailable"`.

Close criteria:

- A non-smoke artifact directory exists under `benchmark-suite/artifacts/`.
- Every completed task has both enabled and disabled results.
- `validate_run.py` passes for the bundle.
- `render_report.py` produces `summary.csv` and `report.md`.
- The report states runtime, turns, acceptance, and token availability without
  overstating savings.

### GAP-BENCH-002: Evidence Safety

Dimension:

- Evidence safety
- Generated knowledge
- Temporal query

Current status: `ready-to-run`

Current evidence:

- Design pack: `benchmark-suite/evidence_safety/`
- Regression tests cover pieces of provenance rendering, source-id display,
  generated-only search isolation, and historical truth boundaries.
- Packet docs contain user-visible transcript rules.
- No completed artifact bundle currently measures evidence-safety behavior.

Why this remains open:

- Tests prove narrow invariants, not agent behavior under realistic evidence
  pressure.
- Packet evidence can be near-neighbor evidence; it must not be promoted into
  stronger claims.
- Generated prose and historical truth need adversarial prompts that verify the
  agent abstains or qualifies claims.

Required work:

- Run the `evidence_safety` design pack.
- Define forbidden claims for each task before running.
- Store transcripts, tool calls if visible, final answer, and acceptance notes.

Close criteria:

- A benchmark artifact bundle demonstrates that the agent does not overclaim
  when evidence is weak, generated-only, missing, or historical.
- The report separates "evidence found" from "claim safely supported".
- The report has at least one negative or abstention case.

## P1 Gaps

### GAP-BENCH-003: Temporal Product Query

Dimension:

- Temporal query
- Memory runtime
- Evidence safety

Current status: `ready-to-run`

Current evidence:

- Design pack: `benchmark-suite/temporal_product_query/`
- `docs/benchmark/v160-baseline.md` covers LongMemEval temporal-reasoning as
  retrieval quality.
- Unit and integration tests cover current/history/supersede mechanics.
- v3.3 temporal query and supersede explainability is planning-only.

Why this remains open:

- LongMemEval temporal-reasoning is not the same as product-level temporal query.
- There is no completed artifact bundle for `current`, `history`, `as_of`,
  supersede timeline, or abstention behavior.

Required work:

- Run the `temporal_product_query` design pack.
- Require source-backed answers and explicit history/current separation.

Close criteria:

- The benchmark report proves that temporal queries do not mix current and
  historical truth.
- The report includes at least one ambiguous query where the correct behavior is
  to abstain or ask for scope.

### GAP-BENCH-004: Warm Path Latency Non-Smoke

Dimension:

- Performance
- Memory runtime

Current status: `ready-to-run`

Current evidence:

- Historical docs:
  - `docs/benchmark/v151-baseline.md`
  - `docs/benchmark/v160-baseline.md`
- Suite driver:
  `benchmark-suite/latency_warm_path/driver.py`
- Existing artifact is smoke only:
  `benchmark-suite/artifacts/2026-06-06-latency_warm_path-smoke/`

Why this remains open:

- The smoke run has only `3` samples.
- `search_hybrid` fell back to FTS because embeddings were unavailable.
- It is useful as driver validation, not as a public warm-path latency matrix.

Required work:

- Run a non-smoke latency pass with enough samples for stable p50/p95.
- Record corpus size, warmup count, fallback reason, and effective mode.
- If hybrid falls back, label it as fallback rather than hybrid performance.

Close criteria:

- A non-smoke artifact bundle exists.
- The report includes p50, p95, p99, max, fallback status, and sample count.
- Any public claim says whether results are synthetic, warm, cold, or fallback.

## P2 Gaps

### GAP-BENCH-005: Generated Knowledge Cache and Freshness

Dimension:

- Generated knowledge
- Evidence safety
- Observability

Current status: `ready-to-run`

Current evidence:

- Design pack: `benchmark-suite/generated_knowledge_freshness/`
- v3.2 generated knowledge compiler is planning-only.
- Current tests mainly verify generated material does not contaminate truth or
  default search.

Why this remains open:

- Source maps, atomic claims, incremental generated cache, and freshness metrics
  are not yet shipped as stable benchmark targets.

Required work:

- Wait until v3.2 product surfaces exist.
- Then benchmark source-map completeness, freshness detection, generated-cache
  invalidation, and citation validation.

Close criteria:

- Generated prose is benchmarked as generated context, not confirmed truth.
- The report includes freshness and source-map failure cases.

### GAP-BENCH-006: Auto Maintenance Effectiveness

Dimension:

- Auto maintenance
- Observability
- Evidence safety

Current status: `blocked-by-product`

Current evidence:

- Design pack: `benchmark-suite/auto_maintenance_effectiveness/`
- Metabolism, auto-review, candidate health, and maintenance hints have tests.
- v3.1 Auto Dream Memory Maintenance now exposes `/hm:dream`,
  DreamRun/DreamItem ledger, MCP `dream_ledger` / `dream_run` /
  `dream_auto_tick` / `undo_dream_item`, and default-off config gates.

Why this remains open:

- No completed artifact bundle measures automatic maintenance effectiveness,
  false positives, undoability, or user-visible ledger behavior.
- Product tests prove the shape of the surface; they do not prove benchmark
  effectiveness.

Required work:

- Run the `auto_maintenance_effectiveness` design pack against the v3.1
  `/hm:dream` surface.
- Benchmark merge, stale, supersede, reject, undo, and ledger audit flows.

Close criteria:

- Report includes true positives, false positives, false successes, recovery,
  and user-visible audit trail.
- No benchmark claim implies silent truth mutation.

### GAP-BENCH-007: Runtime Health and Observability

Dimension:

- Observability
- Cost discipline
- Performance

Current status: `blocked-by-product`

Current evidence:

- Design pack: `benchmark-suite/runtime_health_observability/`
- `health_summary`, `doctor`, `candidate_health`, and maintenance hints are
  tested.
- v3.4 Runtime Health, Cost Discipline, and Regression Gates is planning-only.

Why this remains open:

- There is no runtime-health benchmark result that covers version drift, false
  success, token budget visibility, or regression gate behavior.

Required work:

- Wait until v3.4 health surfaces are stable.
- Benchmark version drift, stale index diagnosis, missing transport diagnosis,
  budget overrun detection, and regression gate reporting.

Close criteria:

- Report shows diagnosis quality and false-success count.
- Cost discipline is tracked as its own class, not folded into observability.

## Extraction Summary

Immediate execution order:

1. `GAP-BENCH-001`: client enabled-vs-disabled paired runs.
2. `GAP-BENCH-002`: evidence-safety artifact bundle.
3. `GAP-BENCH-003`: temporal product-query artifact bundle.
4. `GAP-BENCH-004`: non-smoke warm-path latency run.

Deferred until product surfaces stabilize:

1. `GAP-BENCH-005`: generated knowledge cache and freshness.
2. `GAP-BENCH-006`: auto maintenance effectiveness.
3. `GAP-BENCH-007`: runtime health and observability.
