## Why

Structured truth currently has no validity window. If an old session says "use Vue"
and a newer confirmed memory says "use React", search and wake can surface both
as equally current truth. v1.7.0 adds the minimum temporal contract needed to
separate current facts from historical facts without deleting audit evidence.

## What Changes

- Add temporal fields to truth-like structured entities:
  `valid_from`, `valid_to`, `recorded_at`, `supersedes`, `superseded_by`
- Persist the fields in SQLite and JSON blobs with legacy-safe defaults
- Make default structured reads current-only: `valid_to IS NULL OR valid_to > now`
- Add explicit `include_history` read paths for callers that need current plus
  historical truth

## Impact

- Default search / wake behavior becomes safer because stale truth is excluded
- Historical truth remains auditable and can be returned explicitly
- Supersede candidates in v1.7.1 can build on real validity fields instead of
  ad hoc status strings
