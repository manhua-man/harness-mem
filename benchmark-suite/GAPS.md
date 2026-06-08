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

Current status: `closed`

Current evidence:

- Methodology: `docs/benchmark/agent-enabled-vs-disabled.md`
- Suite collection: `client_enabled_vs_disabled`
- Prompt pack: `benchmark-suite/client_enabled_vs_disabled/prompts.json`
- Acceptance checklist:
  `benchmark-suite/client_enabled_vs_disabled/acceptance_checklist.md`
- Codex paired-run harness:
  `benchmark-suite/client_enabled_vs_disabled/run_codex_pair.py`
- The harness now writes result schema v2 with a structured `token_usage`
  envelope and optional named token/cost sidecars; legacy accepted runs without
  the envelope remain valid but cannot support token/cost deltas.
- Schema v2 validation checks the token envelope shape and rejects
  `available=true` token records that have no numeric token/cost evidence.
- `benchmark-suite/tools/extract_codex_token_usage.py` can export a numeric
  sidecar from Codex JSONL `token_count` events without copying prompt or
  tool-output text.
- `benchmark-suite/tools/apply_token_usage_sidecars.py` can apply those
  sidecars to `results/*.json` and upgrade the run manifest to result schema v2
  when every result has token evidence.
- Earlier smoke-only artifacts were removed after the completed paired bundle
  replaced them; they are not closure evidence.
- Attempted Codex non-interactive paired run on 2026-06-08 reached the Codex
  service but failed with `429 Too Many Requests`; no paired result is claimed
  from that attempt.
- Completed paired artifact:
  `benchmark-suite/artifacts/2026-06-08-client_enabled_vs_disabled-codex-paired-t1-t3-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-client_enabled_vs_disabled-codex-paired-t1-t3-01`
  returned `OK: validated 6 result files for client_enabled_vs_disabled`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-client_enabled_vs_disabled-codex-paired-t1-t3-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `3` paired tasks: `T1`, `T2`, and `T3`.
- Each completed task has both enabled and disabled results.
- All `6` result files are accepted by the predeclared task rubric.
- Disabled results record empty `memory_calls` lists.
- Token totals remain `unavailable`, so no token-saving claim is supported.
- Enabled memory calls are recorded, including cases where the Codex exec
  environment exposed or attempted the read surface but could not complete the
  MCP call; the report should be read as Codex paired task behavior, not a
  strong memory-retrieval uplift claim.

Completed work:

- Added a Codex paired-run harness and output schema.
- Ran a 3-task paired bundle with fixed client, model, workspace, prompt, and
  repo state.
- Recorded transcripts, result files, `summary.csv`, and `report.md`.
- Recorded token totals as `"unavailable"` because the client did not expose a
  stable token counter.
- Added a follow-up token/cost evidence path: future paired runs can provide
  `--token-usage-dir` sidecars, and schema v2 validation requires a meaningful
  `token_usage` envelope.
- Added a Codex token-count extractor for building those sidecars from numeric
  session usage events when the client records them.
- Added a sidecar application step so extracted token evidence can be rendered,
  validated, and compared without manual result editing.

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

Current status: `closed`

Current evidence:

- Design pack: `benchmark-suite/evidence_safety/`
- Regression tests cover pieces of provenance rendering, source-id display,
  generated-only search isolation, and historical truth boundaries.
- Packet docs contain user-visible transcript rules.
- Completed guarded artifact:
  `benchmark-suite/artifacts/2026-06-08-evidence_safety-codex-guarded-e1-e5-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-evidence_safety-codex-guarded-e1-e5-01`
  returned `OK: validated 5 result files for evidence_safety`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-evidence_safety-codex-guarded-e1-e5-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `E1` through `E5` under the `guarded` condition.
- All `5` result files are accepted by the predeclared task rubric.
- The result schema records `evidence_found`, `safe_claim`, and
  `forbidden_claim_check`, separating evidence from claim strength.
- The run includes negative/abstention pressure:
  `E5` qualifies a stronger completed/closed benchmark claim as insufficiently
  evidenced, rather than converting partial artifacts into completion.
- `E2` preserves the generated-only boundary, `E3` preserves near-neighbor
  artifact strength, and `E4` separates current from historical truth.

Completed work:

- Added a guarded Codex runner and output schema for the evidence-safety pack.
- Ran the `E1`-`E5` design pack.
- Stored transcripts, visible call records, final answers, and acceptance notes.

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

Current status: `closed`

Current evidence:

- Design pack: `benchmark-suite/temporal_product_query/`
- `docs/benchmark/v160-baseline.md` covers LongMemEval temporal-reasoning as
  retrieval quality.
- Unit and integration tests cover current/history/supersede mechanics.
- v3.3 temporal query and supersede explainability surfaces have shipped; this
  benchmark measures product-level behavior beyond LongMemEval retrieval
  quality.
- Completed temporal artifact:
  `benchmark-suite/artifacts/2026-06-08-temporal_product_query-codex-temporal-tq1-tq5-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-temporal_product_query-codex-temporal-tq1-tq5-01`
  returned `OK: validated 5 result files for temporal_product_query`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-temporal_product_query-codex-temporal-tq1-tq5-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `TQ1` through `TQ5` under the
  `temporal_guarded` condition.
- All `5` result files are accepted by the predeclared task rubric.
- Results record explicit `current_truth`, `historical_truth`, and
  `missing_evidence` fields.
- `TQ1` and `TQ2` separate current default reads from explicit history reads.
- `TQ3` qualifies `as_of` support by product surface and evidence.
- `TQ4` explains supersede direction without deleting audit history.
- `TQ5` identifies ambiguous temporal scope and requests clarification instead
  of merging current/history/as_of into one claim.

Completed work:

- Added a temporal Codex runner and output schema.
- Ran the `TQ1`-`TQ5` design pack.
- Stored transcripts, visible call records, final answers, and acceptance notes.

Close criteria:

- The benchmark report proves that temporal queries do not mix current and
  historical truth.
- The report includes at least one ambiguous query where the correct behavior is
  to abstain or ask for scope.

### GAP-BENCH-004: Warm Path Latency Non-Smoke

Dimension:

- Performance
- Memory runtime

Current status: `closed`

Current evidence:

- Historical docs:
  - `docs/benchmark/v151-baseline.md`
  - `docs/benchmark/v160-baseline.md`
- Suite driver:
  `benchmark-suite/latency_warm_path/driver.py`
- Earlier smoke-only artifacts were removed after the completed non-smoke
  bundle replaced them; they are not closure evidence.
- Completed non-smoke artifact:
  `benchmark-suite/artifacts/2026-06-08-latency_warm_path-local-nonsmoke-offline-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-latency_warm_path-local-nonsmoke-offline-01`
  returned `OK: validated 3 result files for latency_warm_path`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-latency_warm_path-local-nonsmoke-offline-01/report.md`
  and `summary.csv`.

Why this is closed:

- The non-smoke run uses `40` samples with `10` warmup runs on an isolated
  synthetic corpus of `300` memory entries and `150` observations.
- `search_fts`, `search_hybrid`, and `wake_synthetic` all completed with
  `error_count=0`.
- `search_hybrid` is explicitly labeled `effective_mode=fts` with
  `fallback_reason=embedding not available`, so the report does not overclaim
  true hybrid-vector performance.

Completed work:

- Ran a non-smoke latency pass with enough samples for p50/p95/p99/max.
- Recorded corpus size, warmup count, fallback reason, and effective mode.
- Rendered a report that states synthetic warm-path status and fallback status.

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

Current status: `closed`

Current evidence:

- Design pack: `benchmark-suite/generated_knowledge_freshness/`
- v3.2 generated knowledge compiler has shipped source maps, atomic claims,
  citation validation, incremental compile metrics, and freshness/status
  visibility.
- Current tests mainly verify generated material does not contaminate truth or
  default search.
- Completed generated-knowledge artifact:
  `benchmark-suite/artifacts/2026-06-08-generated_knowledge_freshness-codex-generated-gk1-gk5-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-generated_knowledge_freshness-codex-generated-gk1-gk5-01`
  returned `OK: validated 5 result files for generated_knowledge_freshness`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-generated_knowledge_freshness-codex-generated-gk1-gk5-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `GK1` through `GK5` under the
  `generated_guarded` condition.
- All `5` result files are accepted by the predeclared task rubric.
- Results record `generated_claims`, `source_map_status`, `freshness_status`,
  and `truth_boundary` fields.
- `GK1` correctly reports incomplete source-map coverage for generated prose
  instead of treating generated prose as self-evidencing.
- `GK2` keeps generated-only claims out of confirmed truth.
- `GK3` detects stale generated cache after source truth changes.
- `GK4` identifies the affected generated claim/section without discarding
  unrelated generated content.
- `GK5` rejects citation laundering and separates unsupported citations from
  missing or stale citations.

Completed work:

- Updated the design pack from blocked to ready after v3.2 shipped.
- Added a generated-knowledge Codex runner and output schema.
- Ran the `GK1`-`GK5` design pack.
- Stored transcripts, visible call records, final answers, and acceptance notes.

Close criteria:

- Generated prose is benchmarked as generated context, not confirmed truth.
- The report includes freshness and source-map failure cases.

### GAP-BENCH-006: Auto Maintenance Effectiveness

Dimension:

- Auto maintenance
- Observability
- Evidence safety

Current status: `closed`

Current evidence:

- Design pack: `benchmark-suite/auto_maintenance_effectiveness/`
- Metabolism, auto-review, candidate health, and maintenance hints have tests.
- v3.1 Auto Dream Memory Maintenance now exposes `/hm:dream`,
  DreamRun/DreamItem ledger, MCP `dream_ledger` / `dream_run` /
  `dream_auto_tick` / `undo_dream_item`, and default-off config gates.
- Completed auto-maintenance artifact:
  `benchmark-suite/artifacts/2026-06-08-auto_maintenance_effectiveness-codex-maintenance-am1-am6-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-auto_maintenance_effectiveness-codex-maintenance-am1-am6-01`
  returned `OK: validated 6 result files for auto_maintenance_effectiveness`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-auto_maintenance_effectiveness-codex-maintenance-am1-am6-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `AM1` through `AM6` under the
  `maintenance_guarded` condition.
- All `6` result files are accepted by the predeclared task rubric.
- Results record `maintenance_actions`, `before_state`, `after_state`,
  `ledger_evidence`, `undo_or_recovery`, and `truth_mutation_check`.
- `AM1` covers duplicate merge suggestion and provenance preservation.
- `AM2` covers stale truth suggestion and visible rationale.
- `AM3` covers supersede direction and history retention.
- `AM4` covers a false-positive rejection path.
- `AM5` covers undo / rollback evidence and failure handling.
- `AM6` covers user-visible ledger explainability.
- The artifact is a guarded repo/test-evidence benchmark, not a live mutation
  run on the current worktree; public claims should describe audited maintenance
  behavior and undo evidence, not broad production effectiveness.

Completed work:

- Updated stale design hints to current v3.1 docs/tests.
- Added an auto-maintenance Codex runner and output schema.
- Ran the `AM1`-`AM6` design pack.
- Stored transcripts, visible call records, final answers, and acceptance notes.

Close criteria:

- Report includes true positives, false positives, false successes, recovery,
  and user-visible audit trail.
- No benchmark claim implies silent truth mutation.

### GAP-BENCH-007: Runtime Health and Observability

Dimension:

- Observability
- Cost discipline
- Performance

Current status: `closed`

Current evidence:

- Design pack: `benchmark-suite/runtime_health_observability/`
- `health_summary`, `doctor`, `candidate_health`, and maintenance hints are
  tested.
- v3.4.4 ships the local MCP surface cost observer, `surface_cost_report`,
  runtime health report, version drift visibility, benchmark regression gates,
  and cost budget policy.
- Completed runtime-health artifact:
  `benchmark-suite/artifacts/2026-06-08-runtime_health_observability-codex-health-rh1-rh6-01/`
- Validation:
  `python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/2026-06-08-runtime_health_observability-codex-health-rh1-rh6-01`
  returned `OK: validated 6 result files for runtime_health_observability`.
- Rendered report:
  `benchmark-suite/artifacts/2026-06-08-runtime_health_observability-codex-health-rh1-rh6-01/report.md`
  and `summary.csv`.

Why this is closed:

- The completed bundle covers `RH1` through `RH6` under the `health_guarded`
  condition.
- All `6` result files are accepted by the predeclared task rubric.
- Results keep runtime health, version drift, cost discipline, regression gate,
  transport diagnosis, and false-success accounting as separate fields.
- `RH1` separates healthy and degraded surfaces.
- `RH2` names compared versions/schema ids and explicit drift status.
- `RH3` reports cost budget metadata separately from observability.
- `RH4` checks benchmark regression dimensions against an explicit threshold.
- `RH5` diagnoses broken MCP transport without obsolete daily CLI fallback.
- `RH6` records `false_success_count=1`: process cleanup `SUCCESS` text after
  a `429 Too Many Requests` failure is counted as false success without
  before/after recovery evidence.

Completed work:

- Added a runtime-health Codex runner and output schema.
- Ran the `RH1`-`RH6` design pack.
- Stored transcripts, visible call records, final answers, and acceptance notes.
- Re-rendered and validated the completed bundle.

Close criteria:

- Report shows diagnosis quality and false-success count.
- Cost discipline is tracked as its own class, not folded into observability.
- All `RH1`-`RH6` tasks have result files and transcripts.

## Extraction Summary

Immediate execution order:

All benchmark gaps are closed.

Closed:

1. `GAP-BENCH-001`: client enabled-vs-disabled paired runs.
2. `GAP-BENCH-002`: evidence-safety artifact bundle.
3. `GAP-BENCH-003`: temporal product-query artifact bundle.
4. `GAP-BENCH-004`: non-smoke warm-path latency run.
5. `GAP-BENCH-005`: generated knowledge cache and freshness.
6. `GAP-BENCH-006`: auto maintenance effectiveness.
7. `GAP-BENCH-007`: runtime health and observability.
