## Why

The shipped release line has already progressed through `v2.9.27`, but the
high-visibility baseline summary near the top of `docs/roadmap-status.md` still
enumerated only through `v2.9.11`.

That makes one of the first status summaries a reader sees materially lag behind
the actual shipped line.

## What Changes

- Update the top baseline summary in `docs/roadmap-status.md` so it treats
  `v2.9.0–v2.9.27` as one completed release train.
- Add a focused regression test that fails fast if the summary drifts back to
  the older `v2.9.11` cutoff wording.

## Impact

- Readers who skim only the top baseline summary now get the current shipped
  truth.
- Future edits that truncate the high-visibility baseline summary back to the
  older cutoff fail fast in CI.
