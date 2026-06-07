# Acceptance Checklist: `retrieval_diagnostics`

Use this checklist before accepting any RD1-RD5 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `retrieval_diagnostics`.
- [ ] Baseline and candidate runs are identified.
- [ ] The benchmark delta being diagnosed is recorded.
- [ ] Candidate quality is separated from benchmark quality.
- [ ] Representative misses or changed decisions are stored under `notes/` or
      `results/`.

## RD1: Fusion Ablation

Pass requires all of:

- [ ] Baseline and candidate fusion settings are named.
- [ ] Per-query changes are recorded.
- [ ] Aggregate change is tied to representative decisions.

Primary failure signals:

- Fusion is blamed without showing changed ranking behavior.

## RD2: Stem Fallback Impact

Pass requires all of:

- [ ] Stem fallback on/off behavior is compared.
- [ ] Queries helped and hurt by fallback are identified.
- [ ] Latency impact is recorded if available.

Primary failure signals:

- Fallback is assumed helpful without miss/hit evidence.

## RD3: Temporal Failure Bucket

Pass requires all of:

- [ ] Temporal misses are bucketed.
- [ ] Current/history/as_of confusion is separated from lexical retrieval miss.
- [ ] Representative failures are included.

Primary failure signals:

- All temporal failures are treated as the same retrieval bug.

## RD4: Candidate Ordering

Pass requires all of:

- [ ] Ranking order before and after change is compared.
- [ ] Correct answer location is recorded.
- [ ] Top-k sensitivity is reported when relevant.

Primary failure signals:

- Recall delta is reported without rank evidence.

## RD5: Scenario Validity

Pass requires all of:

- [ ] Checks whether the replay scenario is valid and discriminative.
- [ ] Identifies malformed prompts, missing answers, or non-distinguishing
      fixtures.
- [ ] Does not recommend model/runtime changes before scenario validity is
      checked.

Primary failure signals:

- `delta=0` is treated as conclusion without checking benchmark quality.
