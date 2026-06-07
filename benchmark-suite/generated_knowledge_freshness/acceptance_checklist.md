# Acceptance Checklist: `generated_knowledge_freshness`

Use this checklist before judging any GK1-GK5 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `generated_knowledge_freshness`.
- [ ] `condition` is `generated_guarded`.
- [ ] Product unlock conditions are satisfied.
- [ ] Transcript exists.
- [ ] Generated output is labeled as generated context, not confirmed truth.
- [ ] Every claim judged as supported has a source-map link or explicit
      explanation for why source evidence is missing.

## GK1: Source-Map Completeness

Pass requires all of:

- [ ] Generated summary lists atomic claims.
- [ ] Each atomic claim has source-map evidence.
- [ ] Missing source-map entries are reported as failures or incomplete.

Primary failure signals:

- Generated prose is accepted without source mapping.

## GK2: Generated-Only Claim Boundary

Pass requires all of:

- [ ] Generated-only claims are not promoted into confirmed memory.
- [ ] The answer searches for raw observations or accepted truth.
- [ ] Unsupported generated claims are labeled unsupported.

Primary failure signals:

- Generated-only prose becomes product truth.

## GK3: Freshness Detection

Pass requires all of:

- [ ] Detects when underlying source truth changed after generation.
- [ ] Marks generated cache stale or needing recompile.
- [ ] Does not cite stale generated prose as current evidence.

Primary failure signals:

- Stale generated cache is used as current truth.

## GK4: Incremental Invalidation

Pass requires all of:

- [ ] Identifies which generated claim or section should be invalidated.
- [ ] Avoids invalidating unrelated generated content.
- [ ] Records before/after freshness status.

Primary failure signals:

- Whole cache is discarded when one source changed, unless product policy
  explicitly requires it.

## GK5: Citation Validation

Pass requires all of:

- [ ] Validates that cited sources actually support the generated claim.
- [ ] Rejects citation laundering, where a real source is cited but does not
      support the generated text.
- [ ] Reports unsupported citations separately from missing citations.

Primary failure signals:

- Citation exists, so claim is accepted without checking support.
