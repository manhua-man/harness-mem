## Why

The first group of completed `v2.9` slices in `docs/roadmap-v29.md` still
pointed at `openspec/changes/v29xx...` paths, even though those changes had
already been archived. That makes completed work look like it still lives in
the active change tree.

This is a pointer-truth problem in a high-visibility roadmap doc.

## What Changes

- Update `docs/roadmap-v29.md` so completed early `v29` slices (`v290`–`v2912`)
  point at their `openspec/changes/archive/...` paths.
- Add a focused regression test that rejects those stale active-change paths.
- Update release writeback for `v2.9.44`.

## Impact

- Readers now get archive-accurate OpenSpec pointers from the `v2.9` roadmap.
- Future edits that reintroduce stale active-change links fail fast in CI.
