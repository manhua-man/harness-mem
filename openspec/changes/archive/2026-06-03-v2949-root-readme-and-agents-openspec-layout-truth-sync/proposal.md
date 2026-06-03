## Why

`docs/README.md` already distinguished:

- `openspec/specs/`
- `openspec/changes/`
- `openspec/changes/archive/`

But the repo root `README.md` and `AGENTS.md` still described OpenSpec as a
single `openspec/` bucket. That keeps the highest-visibility repo entry points
out of sync with the current source hierarchy truth.

## What Changes

- Update root `README.md` to list the three OpenSpec layers explicitly.
- Update `AGENTS.md` repo map to do the same.
- Add a focused regression test guarding both files.
- Update release writeback for `v2.9.49`.

## Impact

- The highest-visibility repo entry points now describe the OpenSpec layout accurately.
- Main specs, active changes, and archived changes are no longer blended together.
- CI guards this root-level docs truth against regression.
