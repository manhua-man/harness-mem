## Why

The completion matrix in `docs/roadmap-status.md` still carried historical
`当前收口基线` labels on older release rows such as `v2.8.2` and `v2.9.8`.

Those labels were only true at the time those releases shipped. In current-truth
status documentation, they are now stale and misleading.

## What Changes

- Rewrite historical matrix rows like `v2.8.2` and `v2.9.8` from `当前收口基线`
  to `已完成`.
- Add a focused regression test that fails fast if older rows drift back to the
  historical baseline label.

## Impact

- Readers of the current status matrix now see stable current-truth statuses.
- Future edits that restore stale baseline labels on historical rows fail fast
  in CI.
