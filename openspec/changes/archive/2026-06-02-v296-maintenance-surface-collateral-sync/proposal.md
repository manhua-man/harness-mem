## Why

The main CLI spec, stale-surface guard, and shell completion were already
updated through v2.9.5, but two important collateral surfaces still describe
the older maintenance console:

- `openspec/specs/mcp/spec.md` still says the CLI only keeps
  `init/quickstart/doctor/import/purge/maintenance`
- `docs/v2-user-test-packet.md` still says the allowed maintenance CLI set ends
  at `import`

That leaves the repo with a split source of truth for the same boundary.

## What Changes

- Sync the MCP spec preamble to the current maintenance CLI surface.
- Sync the v2 user test packet's maintenance-command expectation to include
  `config` and `integration`.
- Record the v2.9.6 slice in roadmap, status, changelog, and version metadata.

## Impact

- The remaining high-visibility collateral now matches the shipped CLI truth.
- User-facing testing guidance no longer flags supported maintenance commands as
  if they were missing or disallowed.
- The maintenance-only boundary stays consistent across specs, docs, tests, and
  generated surfaces.
