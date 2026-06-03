## Why

`docs/README.md` still described the OpenSpec surface as if design specs simply
lived in `openspec/specs/` and `openspec/changes/`. That wording is too loose:

- `openspec/specs/` is the current main spec truth
- `openspec/changes/` is only for active changes
- `openspec/changes/archive/` holds completed change records

Without that distinction, the docs index blurs stable spec truth, in-flight
change work, and historical archive records.

## What Changes

- Update `docs/README.md` to spell out the three-layer OpenSpec layout.
- Add a focused regression test rejecting the old two-directory wording.
- Update release writeback for `v2.9.47`.

## Impact

- High-visibility docs now describe the OpenSpec layout accurately.
- Readers can distinguish current main specs from active and archived changes.
- CI guards this index-level truth against regression.
