## Why

The shipped runtime already uses
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface. But `AGENTS.md`, one of the primary repo truth files
for future agents, still described an older chain based on `list_candidates`
plus confirm/reject actions as if that were the normal distill path.

That leaves one of the highest-priority collaboration truth files out of sync
with the review surface the runtime actually wants agents to follow.

## What Changes

- Update `AGENTS.md` so its distill mainline points directly to
  `auto_review_candidates(project_name=<project>, apply=true)`.
- Keep `list_candidates` and `confirm_*` / `reject_*` only as explicit repair
  or drilldown tooling.
- Add a focused regression test that fails fast if `AGENTS.md` drifts back to
  the older mainline.

## Impact

- Future agents that load `AGENTS.md` will be steered to the shipped review
  surface instead of the stale one.
- Future doc edits that reintroduce the older manual-review mainline fail fast
  in CI.
