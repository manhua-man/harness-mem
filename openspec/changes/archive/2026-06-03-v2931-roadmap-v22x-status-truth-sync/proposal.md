## Why

`docs/roadmap-v22x.md` still described the line as `规划中`, even though `v2.2`
has long since been completed and reflected as complete in current-truth status
artifacts.

That leaves a high-visibility historical roadmap with stale status wording.

## What Changes

- Update the top status line in `docs/roadmap-v22x.md` to reflect that `v2.2.0`
  is complete.
- Add a focused regression test that fails fast if the older `规划中` wording
  returns.

## Impact

- Readers now see the current shipped truth when consulting the v2.2 roadmap.
- Future edits that reintroduce the stale planning-state wording fail fast in
  CI.
