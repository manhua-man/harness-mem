# Acceptance Checklist: `memory_shortcut_vs_source_recovery`

Use this checklist before accepting any memory-shortcut result.

## Global Checks

- [ ] `benchmark_id` is `memory_shortcut_vs_source_recovery`.
- [ ] `condition` is exactly `enabled` or `disabled`.
- [ ] Client, model, workspace path, prompt text, and repo state match across
      each enabled/disabled pair.
- [ ] `token_usage.available=true` on both sides, with a named source and a
      numeric `total`.
- [ ] When available, `input`, `cached_input`, `output`, and `reasoning` token
      fields are preserved so the cache-adjusted diagnostic proxy can be
      rendered.
- [ ] Runtime, prompt turns, follow-up count, memory calls, repo/source calls,
      read-file count, and cited source paths are recorded.
- [ ] Enabled results record the memory packet or memory call used before source
      verification.
- [ ] Enabled long-source results stay within the declared source verification
      budget, unless the result explicitly records a contradiction or missing
      evidence reason.
- [ ] Disabled results record an empty `memory_calls` list and contain no
      harness-mem read/write calls.
- [ ] Negative controls stay within their local-evidence budgets and do not
      expand into broad repo investigation.
- [ ] Both answers satisfy the same task-specific correctness rubric.
- [ ] Enabled answers cite source evidence; memory text alone is not accepted as
      authority.

## Task-Level Pass

Pass requires all of:

- [ ] The answer includes every required fact.
- [ ] No forbidden claim is present.
- [ ] The answer cites the required source class: docs, release snapshot,
      archived session packet, benchmark artifact, or current local file.
- [ ] Enabled mode uses memory as a shortcut and performs bounded source
      verification.
- [ ] Disabled mode recovers the answer from long source material without memory.
- [ ] Negative-control tasks use only the declared tiny/current local evidence
      surface.

Primary failure signals:

- Enabled mode treats memory prose as the final authority without source
  verification.
- Disabled mode accidentally uses harness-mem read surfaces.
- A task is answerable from a tiny obvious file path, making the source-recovery
  path non-discriminative.
- A negative-control task performs broad search, full-repo lint/type/test, or
  multi-file diagnosis.
- An enabled long-source task reads more than two source files/artifacts without
  recording a contradiction or missing-evidence reason.
- A broad decision-chain task makes enabled mode read the memory packet and then
  verify every historical source pointer; treat that as diagnostic, not as a
  saving case.
- The result is accepted after changing the rubric post hoc.

## Pair-Level Claim Gate

The benchmark may support a bounded token/cost shortcut claim only when all of
the following are true:

- [ ] At least `6` of `8` long-source tasks pass in both conditions.
- [ ] The median `disabled - enabled` token delta across passed, budget-ok
      long-source pairs is positive by at least `20%`, using total tokens.
- [ ] At least `6` of `8` passed, budget-ok long-source pairs have fewer
      enabled read-file/source-call records than disabled.
- [ ] At least `6` of `8` passed long-source pairs stay within the enabled
      source verification budget.
- [ ] Negative controls do not show a meaningful memory advantage.
- [ ] Both negative controls stay within their local-evidence budget.
- [ ] Every published table names the dataset, source corpus, token source, and
      claim boundary.

The cache-adjusted local token proxy may be cited as diagnostic evidence about
cache pollution or execution-order effects. It does not satisfy the total-token
gate and does not prove real billing savings.

If any condition fails, publish the run as diagnostic evidence only.
