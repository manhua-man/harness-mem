## Why

`docs/roadmap/dream-mechanism-absorption-v151-v17.md` still exposed a bare
`draft` status, even though the related `v1.5.1` - `v1.7` line has long since
shipped and the document now serves as a historical design note rather than an
active roadmap promise.

That leaves a high-visibility historical design draft with stale status
wording.

## What Changes

- Update the top status block in
  `docs/roadmap/dream-mechanism-absorption-v151-v17.md` so it explicitly says
  the file is a historical draft archive and points readers at current-truth
  status artifacts.
- Update `docs/README.md` so `docs/roadmap/` is described as historical roadmap
  proposals / design drafts rather than current version planning.
- Add a focused regression test that fails fast if the historical draft drifts
  back to a bare `draft` label.

## Impact

- Readers can distinguish historical design drafts from active roadmap
  commitments at a glance.
- Future edits that reintroduce the stale bare-draft wording fail fast in CI.
