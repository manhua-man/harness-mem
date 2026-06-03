## Why

`docs/roadmap-v29.md` already documents a long `v2.9.x` release train through
`v2.9.26`, but its top-level theme line still described the whole line as only
`PRD Sync Candidate Surface`.

That under-describes the shipped truth in one of the highest-visibility
roadmap headers in the repo.

## What Changes

- Sync the top-level theme and goal summary in `docs/roadmap-v29.md` to the
  shipped truth: `v2.9` started with PRD sync and then expanded into a
  maintenance / triage / truth-sync release train.
- Add a focused regression test that fails fast if the header drifts back to
  the earlier PRD-only wording.

## Impact

- Readers who skim only the roadmap header now get the current shipped truth.
- Future edits that collapse the theme back to a PRD-only summary fail fast in
  CI.
