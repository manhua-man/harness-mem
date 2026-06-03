## Why

`docs/README.md` still described `roadmap-status.md` as covering `v1.6` through
`v2.9`, even though the current completion matrix explicitly includes `v1.5.x`
as historical completed groundwork.

That leaves a high-visibility docs index with a stale range description.

## What Changes

- Update the `docs/README.md` index line for `roadmap-status.md` so it covers
  `v1.5` through `v2.9`.
- Add a focused regression test that fails fast if the docs index drifts back
  to the older `v1.6` starting point.

## Impact

- Readers now see the correct historical range for the status ledger at a
  glance.
- Future edits that reintroduce the truncated `v1.6` range fail fast in CI.
