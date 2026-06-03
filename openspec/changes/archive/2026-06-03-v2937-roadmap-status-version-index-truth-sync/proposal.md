## Why

`docs/roadmap-status.md` already describes the completed historical range as
`v1.5` through `v2.9`, but its high-visibility version index still started at
`v2.2.x` and still used the label `后续 Roadmap`.

That leaves the status page's version index narrower and more time-skewed than
the page's own current truth.

## What Changes

- Update the version index table in `docs/roadmap-status.md` so it covers
  `v1.5.x` through `v2.9.x`.
- Rename the section header from `后续 Roadmap` to `版本索引`.
- Add a focused regression test that fails fast if the version index drifts
  back to the older `v2.2.x` starting point.

## Impact

- Readers now get a version index whose scope matches the rest of the status
  page.
- Future edits that narrow the version index back to `v2.2+` fail fast in CI.
