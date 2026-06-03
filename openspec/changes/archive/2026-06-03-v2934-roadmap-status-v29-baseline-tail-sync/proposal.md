## Why

`docs/roadmap-status.md` still described the top v2.9 release train summary as
`v2.9.0–v2.9.27`, even though the release train has continued through the
current `2.9.33` version.

That leaves the highest-visibility status summary with a stale release-train
tail.

## What Changes

- Update the top baseline summary in `docs/roadmap-status.md` so the v2.9 train
  tail matches the current shipped version.
- Update `tests/test_roadmap_status_baseline_truth.py` so it follows
  `harness_mem.__version__` instead of a hard-coded older tail.

## Impact

- Readers now see the full current v2.9 release train in the top baseline
  summary.
- Future v2.9.x bumps do not require manual test edits just to advance the tail
  number.
