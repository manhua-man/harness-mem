## Why

The shipped CLI surface already includes `config` and `integration`, and the
main CLI spec was synced in v2.9.3. But the focused stale-surface regression
test still describes the maintenance console as if it ended at
`maintenance`.

That leaves one more current-truth seam: a future doc update could mention
`harness-mem config` or `harness-mem integration` legitimately, while the guard
test's commentary and maintenance allowlist would still represent the old
surface.

## What Changes

- Sync `tests/test_stale_cli_surface.py` commentary and maintenance allowlist to
  the current top-level CLI surface.
- Record the v2.9.4 slice in roadmap and release docs.
- Keep the test focused on forbidding removed daily-memory CLI verbs rather
  than forbidding newly documented maintenance verbs.

## Impact

- The stale-surface guard continues to protect the right boundary.
- Test commentary, OpenSpec, and release docs all describe the same current CLI
  truth.
- Future documentation can mention `config` / `integration` without drifting
  into a false-positive boundary.
