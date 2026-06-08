# Benchmark Results

Artifact-backed result summary for the completed BENCH gap run on 2026-06-09.

This file reports measurable benchmark outcomes, not just artifact existence.
It follows the same evidence discipline as the reference benchmark anchors:
state the task set, metrics, deltas, and unsupported claims.

## Headline

All seven original BENCH gaps plus the v3.8 token-visible / true-hybrid /
retrieval-shootout follow-up artifacts are closed with validated artifact
bundles, but the supported claims are bounded:

- v3.8 `benchmark_matrix_report` now reads the completed artifact results as
  `11` accepted runs, `0` failed runs, `0` unknown runs, with the benchmark gate
  passing for the current artifact set.
- The same matrix exposes machine-readable `claim_readiness` for public claim
  gates. Current readiness is negative for token/cost savings because the
  token-observed pair has a negative disabled-minus-enabled saving delta; true
  vector-hybrid latency and retrieval recall are ready only for bounded local
  synthetic / smoke artifacts.
- `benchmark-suite/release-snapshot.json` carries the tracked accepted-run
  summary for clean checkouts where raw transcripts and result bundles are not
  committed.
- Strong evidence: evidence safety, temporal boundaries, generated-truth
  boundaries, audited maintenance behavior, runtime-health false-success
  accounting.
- Performance evidence: synthetic warm-path FTS/wake plus a local true-hybrid
  probe with no fallback.
- Limited client-value evidence: 3 paired continuation tasks passed in both
  enabled and disabled modes; token totals were unavailable and runtime did not
  show a stable enabled-mode speedup.
- Follow-up evidence path: `client_enabled_vs_disabled` now records a structured
  `token_usage` envelope and accepts named token/cost sidecars for future reruns;
  schema v2 validation rejects named sources with no numeric token/cost field.
  `extract_codex_token_usage.py` can build such sidecars from Codex JSONL
  `token_count` events without copying prompt or tool-output text, and
  `apply_token_usage_sidecars.py` can write them back into result JSON before
  report rendering and validation.
  The 2026-06-09 token-visible artifact records named token totals, but the
  enabled condition used more total tokens than disabled, so it remains a
  no-token-saving-claim run.
- Warm-path latency reports now include a `Vector Hybrid Claim Readiness`
  section, so FTS fallback cannot be silently promoted into a true
  vector-hybrid performance claim.
- True-hybrid retrieval reports now include a `Retrieval Recall Claim Readiness`
  section. Fixture-only rows remain blocked; the 2026-06-09 local smoke run is
  ready only as source-hit recall, not answer correctness.

## Result Scorecard

| Gap | Benchmark | Primary metrics | Result | Supported claim | Unsupported claim |
|---|---|---:|---|---|---|
| BENCH-001 | Client enabled vs disabled | 3 paired tasks plus 1 token-visible pair, all accepted | Original correctness run passed in both modes; 2026-06-09 token-visible pair recorded disabled - enabled token delta `-597494` | Repo-truth continuation tasks can be answered under both conditions; memory calls were gated as intended; token counters can be captured from Codex JSON events | No token-saving claim; no stable speedup claim |
| BENCH-002 | Evidence safety | 5/5 accepted, 30 evidence items recorded, 1 abstention task | No forbidden overclaim in the guarded task set | Agent can preserve evidence strength on missing source, generated-only, near-neighbor, historical, and insufficient evidence prompts | Not a universal guarantee for all agent answers |
| BENCH-003 | Temporal product query | 5/5 accepted, current/history/as_of/missing-evidence fields recorded, 1 ambiguous-scope task | No current/history merge in the guarded task set | Product temporal answers keep current, history, as_of scope, supersede, and ambiguity separate | Not a LongMemEval retrieval score |
| BENCH-004 | Warm path latency | Original 40-sample FTS/wake run plus 2026-06-09 true-hybrid probe | FTS p95 9.901ms; wake p95 9.86ms; true-hybrid probe p95 286.799ms with no fallback | Synthetic warm-path FTS/wake and local true-hybrid latency are measurable with fallback status | Not production latency or broad hardware coverage |
| BENCH-005 | Generated knowledge freshness | 5/5 accepted, 23 generated claims inspected | Source-map incomplete case detected; stale cache detected; citation laundering rejected | Generated prose is kept separate from confirmed truth and source/freshness problems are visible | No claim that generated prose has perfect source-map coverage |
| BENCH-006 | Auto maintenance effectiveness | 6/6 accepted, 19 maintenance actions recorded, 6 truth-mutation checks | Merge, stale, supersede, reject, undo, and ledger paths are auditable in repo/test evidence | Opt-in maintenance paths preserve audit and do not imply silent truth mutation | Not a live production effectiveness or long-run false-positive rate |
| BENCH-007 | Runtime health observability | 6/6 accepted, false_success_count total 2 | Health, drift, cost, gate, transport, and false-success signals are separated | Runtime health can surface false success and cost/gate evidence locally | Not a cloud telemetry or real billing benchmark |
| BENCH-008 | True hybrid retrieval shootout | 3 fixture rows plus 9 local smoke measured rows across fts/vector/hybrid | Contract validates fields; local smoke source-hit recall is 1.0 at R@5 across all three query types and modes | The suite can represent FTS/vector/hybrid evidence and keep default baseline unchanged; local smoke source-hit recall is ready | Not end-to-end answer correctness or broad corpus retrieval quality |

## Release Snapshot Gate

The current v3.8 benchmark matrix reads the accepted artifact state from
`benchmark-suite/artifacts/*/results/*.json` when raw artifact bundles are
present. In a clean checkout without raw artifacts, it falls back to the tracked
`benchmark-suite/release-snapshot.json` summary.

| Metric | Value |
|---|---:|
| Artifact runs | 11 |
| Accepted runs | 11 |
| Failed runs | 0 |
| Unknown runs | 0 |
| Gate passed | true |
| Token/cost saving claim ready | false |
| True vector-hybrid latency claim ready | true |
| Retrieval recall claim ready | true |

This proves the local benchmark artifact set is internally validated and
accepted by the v3.8 matrix gate. It still does not create token-saving,
real-billing, production-latency, broad retrieval-quality, or long-run
production-maintenance claims.

## BENCH-001 Client Continuation Value

Artifact:
`benchmark-suite/artifacts/2026-06-08-client_enabled_vs_disabled-codex-paired-t1-t3-01/`

| Task | Enabled runtime | Disabled runtime | Disabled minus enabled | Enabled memory calls | Disabled memory calls | Outcome |
|---|---:|---:|---:|---:|---:|---|
| T1 | 141.83s | 67.75s | -74.08s | 1 | 0 | both_passed |
| T2 | 117.97s | 151.60s | 33.63s | 2 | 0 | both_passed |
| T3 | 79.53s | 88.26s | 8.73s | 2 | 0 | both_passed |
| Total | 339.33s | 307.61s | -31.72s | 5 | 0 | 3/3 pairs passed |

Interpretation:

- Positive: the disabled condition stayed clean (`memory_calls=[]`), while the
  enabled condition recorded memory-call attempts/usages.
- Positive: all paired task answers passed the predeclared rubric.
- Negative/neutral: total enabled runtime was 10.3% slower on this 3-task run.
- Missing: token totals were `unavailable`, so this run does not support a
  token-saving or cost-saving claim.
- Next artifact requirement: rerun with `token_usage.available=true` on both
  sides of each pair before publishing any token/cost delta.

## BENCH-002 Evidence Safety

Artifact:
`benchmark-suite/artifacts/2026-06-08-evidence_safety-codex-guarded-e1-e5-01/`

| Metric | Value |
|---|---:|
| Tasks accepted | 5/5 |
| Evidence items recorded | 30 |
| Abstention / insufficient-evidence task | 1 (`E5`) |
| Memory calls | 0 |
| Token totals | unavailable |
| Runtime total | 406.74s |

Task coverage:

- `E1`: missing source id weakens provenance but does not prove falsehood.
- `E2`: generated-only material is not confirmed truth.
- `E3`: near-neighbor packet evidence is not promoted into a stronger client
  transcript claim.
- `E4`: historical truth is not reported as current truth.
- `E5`: insufficient evidence is qualified instead of converted into a
  completed benchmark/product claim.

## BENCH-003 Temporal Product Query

Artifact:
`benchmark-suite/artifacts/2026-06-08-temporal_product_query-codex-temporal-tq1-tq5-01/`

| Metric | Value |
|---|---:|
| Tasks accepted | 5/5 |
| Memory calls | 3 |
| Repo calls | 26 |
| `as_of` boundary tasks | 1 (`TQ3`) |
| Ambiguous-scope tasks | 1 (`TQ5`) |
| Runtime total | 439.78s |

Task coverage:

- Default reads prefer current truth.
- Explicit history requests surface historical/superseded truth with labels.
- `as_of` behavior is qualified by actual product surface and timestamp
  evidence.
- Supersede direction is old-to-new, with history retained.
- Ambiguous temporal scope asks for clarification or gives a qualified answer.

## BENCH-004 Warm Path Latency

Artifact:
`benchmark-suite/artifacts/2026-06-08-latency_warm_path-local-nonsmoke-offline-01/`

Run shape:

- `40` samples per operation.
- `10` warmup runs per operation.
- Synthetic corpus: `300` memory entries and `150` observations.
- `error_count=0` for all operations.

| Operation | Effective mode | p50 | p95 | p99 | max | Note |
|---|---|---:|---:|---:|---:|---|
| search_fts | fts | 4.924ms | 9.901ms | 12.309ms | 12.844ms | Synthetic warm FTS |
| search_hybrid | fts | 11.017ms | 13.171ms | 13.970ms | 14.384ms | Requested hybrid, fell back to FTS |
| wake_synthetic | wake_synthetic | 7.510ms | 9.860ms | 10.297ms | 10.516ms | Synthetic wake selection |

Interpretation:

- This supports a bounded synthetic warm-path latency claim.
- It does not support a true vector-hybrid latency claim because
  `search_hybrid` reports `effective_mode=fts` and
  `fallback_reason=embedding not available`.
- The rendered report must say `True vector-hybrid claim ready: yes` before any
  future artifact is used for public vector-hybrid latency claims.

## BENCH-005 Generated Knowledge Freshness

Artifact:
`benchmark-suite/artifacts/2026-06-08-generated_knowledge_freshness-codex-generated-gk1-gk5-01/`

| Metric | Value |
|---|---:|
| Tasks accepted | 5/5 |
| Generated claims inspected | 23 |
| Source-map incomplete cases detected | 1 (`GK1`) |
| Generated-only boundary checks | 1 (`GK2`) |
| Freshness detection checks | 1 (`GK3`) |
| Incremental invalidation checks | 1 (`GK4`) |
| Citation laundering checks | 1 (`GK5`) |
| Runtime total | 444.68s |

Interpretation:

- `GK1` is a safety-positive result because it reports incomplete source-map
  coverage instead of treating generated prose as self-evidencing.
- `GK5` rejects unsupported citations; citation existence alone is not counted
  as evidence.

## BENCH-006 Auto Maintenance Effectiveness

Artifact:
`benchmark-suite/artifacts/2026-06-08-auto_maintenance_effectiveness-codex-maintenance-am1-am6-01/`

| Metric | Value |
|---|---:|
| Tasks accepted | 6/6 |
| Maintenance actions recorded | 19 |
| Truth-mutation checks | 6 |
| False-positive rejection task | 1 (`AM4`) |
| Undo / rollback task | 1 (`AM5`) |
| Runtime total | 1150.48s |

Task coverage:

- `AM1`: duplicate merge suggestion preserves provenance.
- `AM2`: stale truth suggestion has visible rationale.
- `AM3`: supersede direction and history retention are explicit.
- `AM4`: false-positive/unsafe suggestion can be rejected/archived without
  mutating confirmed truth.
- `AM5`: apply/undo evidence is cited from fixtures, including failure handling.
- `AM6`: ledger entries expose action, target, rationale, outcome, and failures.

Interpretation:

- This is a guarded repo/test-evidence benchmark.
- It does not measure long-running production auto-maintenance precision/recall
  or live false-positive rate.

## BENCH-007 Runtime Health Observability

Artifact:
`benchmark-suite/artifacts/2026-06-08-runtime_health_observability-codex-health-rh1-rh6-01/`

| Metric | Value |
|---|---:|
| Tasks accepted | 6/6 |
| False-success count total | 2 |
| Cost-budget overrun checks | 1 primary task (`RH3`) |
| Regression-gate checks | 1 (`RH4`) |
| Transport diagnosis checks | 1 (`RH5`) |
| Runtime total | 1912.76s |

Key data points:

- `RH3`: budget overrun is classified under cost discipline, with
  `budget_tokens=1`, `budget_exceeded=True`, and truncation/drilldown metadata.
- `RH4`: regression gate compares `v161` result to pinned `v160` hybrid-real
  baseline; aggregate delta is `0`, and all six LongMemEval dimensions show
  no regression under the documented threshold.
- `RH6`: a `429 Too Many Requests` failure followed by process cleanup
  `SUCCESS` text is counted as false success, not recovery.

Interpretation:

- Runtime health, drift, cost discipline, regression gate, transport diagnosis,
  and false-success accounting are separated.
- This is not a cloud telemetry benchmark and not a real billing benchmark.

## What This Does Not Prove

- No completed benchmark here proves token savings; Codex token totals were
  unavailable in agent runs.
- No completed benchmark here proves always-on background automation; the
  product boundary remains opt-in host hook / scheduler trigger / Slash / MCP.
- BENCH-004 does not prove vector-hybrid latency because embeddings were not
  available in that run.
- BENCH-006 does not prove production auto-maintenance precision/recall over a
  long time horizon.

## Verification

Each completed artifact validates with:

```text
python benchmark-suite/tools/validate_run.py --run-dir <artifact>
```

Focused repo verification after cleanup:

```text
python -m pytest tests\test_benchmark_gap_backlog_truth.py -q -o cache_dir=.tmp\pytest_cache_cleanup2 --basetemp=.tmp\pytest_tmp_cleanup2
7 passed
```
