## Why

The shipped runtime already uses
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface. But the README's Workflow Skill Boundary diagram still
showed an older chain based on `list_candidates` followed by manual
auto-review/confirm/reject wording.

That leaves one of the highest-visibility project entry documents out of sync
with the distill path the runtime actually wants agents to follow.

## What Changes

- Update the README distill workflow diagram so it points directly to
  `auto_review_candidates(apply=true)`.
- Add a focused regression test that fails fast if the README drifts back to
  the older `list_candidates -> auto-review / confirm / reject` wording.

## Impact

- The README now matches the shipped distill review surface more directly.
- Future README edits that reintroduce the older manual-review chain fail fast
  in CI.
