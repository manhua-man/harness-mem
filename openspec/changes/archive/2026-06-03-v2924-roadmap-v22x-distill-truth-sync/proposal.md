## Why

The shipped runtime already uses
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface. But the historical v2.2 roadmap still described the
distill closed loop as `suggest_* -> list_candidates -> auto-review/confirm/reject`.

That leaves a high-visibility roadmap document out of sync with the current
truth and can still mislead future maintenance work.

## What Changes

- Update the v2.2 roadmap's distill closed-loop contract to point directly to
  `auto_review_candidates(apply=true)`.
- Add a focused regression test that fails fast if the old wording returns.

## Impact

- Historical roadmap guidance now matches shipped truth where it still describes
  the active distill contract.
- Future edits that reintroduce the older mainline fail fast in CI.
