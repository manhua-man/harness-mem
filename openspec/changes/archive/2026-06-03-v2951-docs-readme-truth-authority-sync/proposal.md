## Why

The docs index already listed `roadmap-status.md`, but it did not explicitly say
that current shipped-state truth should be read from:

- `docs/roadmap-status.md`
- `CHANGELOG.md`

That left the docs entry point weaker than the repo root entry points and made
historical roadmap files easier to misread as the current state.

## What Changes

- Update `docs/README.md` to point current shipped-state readers at
  `roadmap-status.md` and `CHANGELOG.md`.
- Add a focused regression test for that authority wording.
- Update release writeback for `v2.9.51`.

## Impact

- The docs entry point now carries the same release-truth authority chain as
  the repo root.
- Historical roadmap files are less likely to be mistaken for current truth.
- CI guards this docs-index authority wording against regression.
