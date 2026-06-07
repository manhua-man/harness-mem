# Acceptance Checklist: `retrieval_quality_longmemeval`

Use this checklist before accepting any LME1-LME4 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `retrieval_quality_longmemeval`.
- [ ] Dataset path is recorded.
- [ ] Command line is recorded.
- [ ] Retrieval mode is recorded.
- [ ] Top-k is recorded.
- [ ] Runtime and per-question runtime are recorded.
- [ ] Per-question-type recall is recorded when the dataset exposes types.
- [ ] Embedding model and fallback state are recorded.
- [ ] Result wording does not compare unlike splits or modes as if they were
      identical.

## LME1: Hybrid Real Baseline

Pass requires all of:

- [ ] Uses the production-like hybrid real path or clearly states fallback.
- [ ] Reports average R@5.
- [ ] Reports per-type R@5.
- [ ] Compares to the pinned v160 baseline only when mode/split/top-k match.

Primary failure signals:

- Hybrid fallback is reported as true hybrid performance.
- Different split or mode is compared as apples-to-apples.

## LME2: FTS Baseline

Pass requires all of:

- [ ] Uses raw FTS mode.
- [ ] Reports average and per-type R@5.
- [ ] Keeps FTS claims separate from hybrid claims.

Primary failure signals:

- FTS results are described as vector or hybrid results.

## LME3: Per-Type Regression Gate

Pass requires all of:

- [ ] Checks aggregate R@5 and per-type deltas.
- [ ] Names the allowed regression threshold.
- [ ] Reports any weak dimension instead of hiding it in aggregate.

Primary failure signals:

- Aggregate pass hides temporal or multi-session regression.

## LME4: Environment Reproducibility

Pass requires all of:

- [ ] Records Python version, platform, dataset snapshot, embedding model, and
      dependency fallback state.
- [ ] Distinguishes deterministic recall from environment-sensitive runtime.

Primary failure signals:

- Runtime comparison omits machine or dependency differences.
