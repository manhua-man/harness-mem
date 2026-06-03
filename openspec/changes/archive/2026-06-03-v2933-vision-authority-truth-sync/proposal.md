## Why

`docs/roadmap-vision-v16-v18.md` and `docs/reference-projects.md` still used
wording that could make readers treat the historical `v1.6` - `v1.8` vision as
current roadmap authority, even though those lines have long since shipped and
current truth now lives in `docs/roadmap-status.md` and `CHANGELOG.md`.

That leaves two high-visibility docs with stale authority wording.

## What Changes

- Update the top status block in `docs/roadmap-vision-v16-v18.md` so it
  explicitly says the file is a historical vision archive and points readers at
  current-truth status artifacts.
- Update `docs/reference-projects.md` so it no longer cites the vision doc as a
  current roadmap authority source.
- Update `docs/README.md` so the vision doc is described as a historical vision
  direction rather than a current roadmap promise.
- Add a focused regression test that fails fast if these docs drift back to the
  older authority wording.

## Impact

- Readers can distinguish historical vision/reference context from current
  shipped-truth status at a glance.
- Future edits that reintroduce stale authority wording fail fast in CI.
