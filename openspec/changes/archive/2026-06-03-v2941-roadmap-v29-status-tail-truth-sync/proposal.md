## Why

The current `v2.9` release train has continued beyond `v2.9.39`, and the body
of `docs/roadmap-v29.md`, `CHANGELOG.md`, and `docs/roadmap-status.md` already
reflect those later slices. But the roadmap header still stopped at
`v2.9.39 已完成`.

That leaves one of the highest-visibility summaries of the `v2.9` line with a
stale tail even though the rest of the repo truth has moved on.

## What Changes

- Update the `docs/roadmap-v29.md` status line so the completed tail reaches
  `v2.9.40`.
- Add a focused regression test that fails fast if the header falls back to the
  older `v2.9.39` tail.
- Update release writeback for `v2.9.41`.

## Impact

- The most visible `v2.9` roadmap header now matches the shipped release-train
  tail.
- Future doc edits that leave the header lagging behind the already-written
  slices fail fast in CI.
