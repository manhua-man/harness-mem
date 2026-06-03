## Why

`docs/roadmap-v25.md` still described the line as `进行中`, and its `v2.5.2`
section still said `待版本收口 / 发版`, even though the `v2.5` line has long
since been formally released and documented elsewhere as complete.

That leaves a high-visibility historical roadmap with outdated status language.

## What Changes

- Update the top status line in `docs/roadmap-v25.md` to reflect that
  `v2.5.0 / v2.5.1 / v2.5.2` are complete.
- Update the `v2.5.2` section so it no longer claims the slice is still pending
  release.
- Add a focused regression test that fails fast if the older `进行中 / 待发版`
  wording returns.

## Impact

- Readers now see the current shipped truth when consulting the v2.5 roadmap.
- Future edits that reintroduce the stale release-state wording fail fast in CI.
