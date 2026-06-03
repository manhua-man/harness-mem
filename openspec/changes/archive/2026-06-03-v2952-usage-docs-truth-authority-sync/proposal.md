## Why

The repo root entry points and docs index already pointed readers at
`roadmap-status.md` and `CHANGELOG.md` for current shipped-state truth, but two
high-visibility usage docs did not:

- `plugins/harness-mem/README.md`
- `docs/best-practices.md`

Those files focused on installation and usage guidance, but without an explicit
authority note they could still be misread as standalone current-truth sources.

## What Changes

- Update the plugin README to point readers at `docs/roadmap-status.md` and
  `CHANGELOG.md`.
- Update `docs/best-practices.md` to do the same.
- Add a focused regression test for both files.
- Update release writeback for `v2.9.52`.

## Impact

- High-visibility usage docs now share the same current-truth authority chain
  as the repo root and docs index.
- Installation and usage guidance is kept separate from shipped-state truth.
- CI guards this usage-doc authority wording against regression.
