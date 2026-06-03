## Why

The repo root entry points explained what the project is and how agents should
work with it, but they did not explicitly say where maintainers should look for
current shipped-state truth. That leaves a gap between:

- historical slice design in the various roadmap files
- current release truth in `docs/roadmap-status.md` and `CHANGELOG.md`

High-visibility root docs should make that authority chain explicit.

## What Changes

- Update root `README.md` to point current shipped-state readers at
  `docs/roadmap-status.md` and `CHANGELOG.md`.
- Update `AGENTS.md` to say the same.
- Add a focused regression test guarding both files.
- Update release writeback for `v2.9.50`.

## Impact

- Maintainers landing on the repo root now have a clear current-truth authority
  path.
- Historical roadmap docs are less likely to be misread as the current shipped
  state.
- CI guards this root-level authority wording against regression.
