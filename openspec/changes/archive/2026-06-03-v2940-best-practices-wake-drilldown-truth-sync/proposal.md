## Why

The shipped runtime already treats MCP `wake(project_name=<project>)` as the
default wake-up surface, and repo-local wake guidance was previously synced to
that contract. But `docs/best-practices.md` still listed `get_task_handoffs`
and `get_confirmed_rules` as if they were normal new-session starting points.

That leaves one of the highest-visibility agent-author guides at a coarser,
older wake granularity than the runtime now expects.

## What Changes

- Update `docs/best-practices.md` so `wake` explicitly covers common new-session
  profile/rules/handoff reads.
- Rephrase `get_task_handoffs` and `get_confirmed_rules` as explicit drilldown
  surfaces for provenance or raw detail, not default wake-up entrypoints.
- Extend the daily-workflow spec wording so best-practices guidance preserves
  this drilldown boundary.
- Add a focused regression test that fails fast if the doc drifts back to the
  older low-level-first wording.

## Impact

- Agent-author guidance now matches the shipped `wake`-first read contract more
  precisely.
- Future doc edits that re-promote low-level wake reads to default entrypoints
  fail fast in CI.
