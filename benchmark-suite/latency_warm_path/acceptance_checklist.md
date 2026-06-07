# Acceptance Checklist: `latency_warm_path`

Use this checklist before accepting any warm-path latency result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `latency_warm_path`.
- [ ] `condition` is `warm`.
- [ ] Sample count and warmup count are recorded.
- [ ] Corpus size or seeded data size is recorded.
- [ ] p50, p95, p99, max, min, mean, and error count are recorded.
- [ ] Effective mode and fallback reason are recorded for hybrid search.
- [ ] Public wording states synthetic/warm/cold/fallback status.

## wake_synthetic

Pass requires all of:

- [ ] Wake synthetic samples complete without errors.
- [ ] Seeded entry/rule/handoff counts are recorded.
- [ ] Result is labeled synthetic.

Primary failure signals:

- Synthetic wake latency is described as real client latency.

## search_fts

Pass requires all of:

- [ ] FTS mode is requested and effective.
- [ ] Result count from last sample is recorded.
- [ ] Error count is zero or errors are explained.

Primary failure signals:

- FTS errors are hidden in aggregate latency.

## search_hybrid

Pass requires all of:

- [ ] Requested mode is hybrid.
- [ ] Effective mode is recorded.
- [ ] Fallback reason is recorded if effective mode is not hybrid.
- [ ] Fallback run is not reported as true hybrid latency.

Primary failure signals:

- FTS fallback is published as hybrid performance.
