## Why

The shipped `v2.9` line no longer describes only `/hm:prd-sync`. It has grown
into a release train that also covers maintenance, triage, collateral truth
sync, focused guards, reflection root resolution, and multiple high-visibility
entrypoint truth-sync slices.

But `docs/README.md` and `docs/roadmap-status.md` still summarized `v2.9` as a
single `PRD sync candidate surface`, which under-described the shipped truth and
could mislead future maintenance work.

## What Changes

- Sync the high-visibility v2.9 index summaries in `docs/README.md` and
  `docs/roadmap-status.md` to the shipped release-train truth.
- Add a focused regression test that fails fast if those indexes collapse `v2.9`
  back to a single-theme summary.

## Impact

- Readers who only consult index pages now get an accurate summary of what
  `v2.9` actually shipped.
- Future edits that narrow the v2.9 summary back to the earlier PRD-only wording
  fail fast in CI.
