## Why

The `docs/roadmap-v29.md` header was being maintained as an ever-growing patch
list. Even after syncing the tail in `v2.9.41`, the header immediately became
stale again on the next release.

That means the document had a current-truth problem in its format, not only in
its latest tail number.

## What Changes

- Replace the patch-by-patch header list with a version-aligned range summary:
  `v2.9.0–v<current> 已完成`.
- Update the focused regression test to read `harness_mem.__version__` so the
  guard follows the shipped version truth automatically.
- Update release writeback for `v2.9.42`.

## Impact

- The highest-visibility `v2.9` roadmap header now stays aligned to current
  truth without requiring one doc-only tail sync per patch release.
- Future edits that reintroduce the brittle patch enumeration fail fast in CI.
