## Why

Several high-visibility historical docs still pointed at active-change-style
OpenSpec paths even though the changes had already been archived:

- `docs/roadmap-v16x.md`
- `docs/roadmap-v17x.md`
- `docs/roadmap-v23.md`
- `tools/session-distill/SKILL.md`

The `session-distill` skill also referenced a nonexistent
`openspec/specs/memory-metabolism/spec.md` path instead of the current main
`metabolism` spec.

## What Changes

- Update the historical roadmap docs so completed slices point at archive
  paths.
- Update `tools/session-distill/SKILL.md` so it points at the archived `v230`
  design and the current main `openspec/specs/metabolism/spec.md`.
- Add a focused regression test covering these archive-pointer and spec-path
  truths.
- Update release writeback for `v2.9.46`.

## Impact

- Historical roadmap docs no longer make shipped work look like it still lives
  in the active change tree.
- The repo-local `session-distill` skill now points readers at a real archived
  design doc plus the current main spec.
- CI now guards this high-visibility pointer truth against regression.
