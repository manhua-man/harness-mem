## Why

`docs/roadmap-v27.md` and `docs/roadmap-v28.md` still pointed completed slices
at `openspec/changes/v27x...` and `v28x...` paths, even though those changes
had already been archived. That makes shipped work look like it still lives in
the active change tree.

This is the same pointer-truth problem already fixed for `roadmap-v29`, just in
the older release-line docs.

## What Changes

- Update `docs/roadmap-v27.md` so completed `v270`–`v272` slices point at their
  archive paths.
- Update `docs/roadmap-v28.md` so completed `v280`–`v282` slices point at their
  archive paths.
- Add a focused regression test that rejects those stale active-change paths.
- Update release writeback for `v2.9.45`.

## Impact

- Readers now get archive-accurate OpenSpec pointers from the `v2.7` and `v2.8`
  roadmap docs.
- Future edits that reintroduce stale active-change links fail fast in CI.
