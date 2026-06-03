## Why

The shipped release line has progressed through `v2.9.26`, but the short
conclusion at the bottom of `docs/roadmap-status.md` still summarized the
versioned roadmap work as if it had only completed through `v2.8`.

That under-describes the current shipped truth in one of the highest-visibility
status summaries in the repo.

## What Changes

- Update the short conclusion in `docs/roadmap-status.md` so it explicitly says
  the line has progressed through `v2.9`.
- Add a focused regression test that fails fast if the summary drifts back to
  the older `completed through v2.8` wording.

## Impact

- Readers who only skim the short conclusion now get the current shipped truth.
- Future edits that collapse the summary back to the older v2.8-only statement
  fail fast in CI.
