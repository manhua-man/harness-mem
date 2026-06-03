## Why

`docs/roadmap-status.md` already covers `v1.5` through `v2.9` in its index and
completion matrix, but the high-visibility short summary at the bottom still
started its narrative from `v2.2`.

That leaves the page's summary scope narrower than the page's own current
truth.

## What Changes

- Update the short-summary paragraph in `docs/roadmap-status.md` so it
  explicitly summarizes the completed line from `v1.5` through `v2.9`.
- Update the focused summary regression test so it rejects drifting back to the
  older `v2.2`-only framing.

## Impact

- Readers now get a short conclusion whose scope matches the actual status
  matrix and docs index.
- Future edits that narrow the summary back to `v2.2+` fail fast in CI.
