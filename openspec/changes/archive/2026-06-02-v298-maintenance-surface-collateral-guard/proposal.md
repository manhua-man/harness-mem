## Why

v2.9.6 and v2.9.7 aligned the MCP spec, user-test packet, README, and
telemetry spec with the shipped maintenance console. But without a focused
guard, those files can drift back independently.

The repo already has a stale daily-CLI scan and shell-completion regression
coverage. The missing piece is a small test that asserts the current
maintenance-surface wording stays aligned across the remaining high-visibility
collateral.

## What Changes

- Add a focused collateral truth test for README, MCP spec, telemetry spec, and
  the v2 user-test packet.
- Record the v2.9.8 slice in roadmap, status, changelog, and version metadata.

## Impact

- Future doc edits that accidentally drop `config` / `integration` from the
  maintenance surface will fail fast.
- The repo's maintenance-console truth is now guarded across both runtime
  surfaces and high-visibility collateral.
