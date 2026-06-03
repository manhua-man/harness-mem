## Why

`docs/roadmap-status.md` already exposes `v1.5` through `v2.9` in its docs
index, version index, and short conclusion, but the top baseline summary still
started at `v2.5`.

That leaves the most visible summary on the page narrower than the rest of the
page's own current truth.

## What Changes

- Update the top baseline summary in `docs/roadmap-status.md` so it explicitly
  summarizes the completed line from `v1.5` through `v2.9`.
- Extend the focused baseline regression test so it also rejects drifting back
  to the older `v2.5` starting point.

## Impact

- Readers now see a top baseline summary whose scope matches the rest of the
  status page.
- Future edits that narrow the baseline summary back to `v2.5+` fail fast in
  CI.
