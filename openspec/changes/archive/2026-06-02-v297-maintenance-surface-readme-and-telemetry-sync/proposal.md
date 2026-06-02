## Why

After v2.9.6, the remaining stale maintenance-surface mentions are now down to
two high-visibility places:

- the README architecture block still summarizes the maintenance console as
  `quickstart, doctor, purge, maintenance, import`
- the telemetry spec still defines CLI telemetry coverage against that same
  older command set

There is also a duplicate sentence in `docs/roadmap-status.md` introduced by
recent writeback churn.

## What Changes

- Sync README's maintenance-console summary to include `config` and
  `integration`.
- Sync the telemetry spec command coverage to the current maintenance console.
- Remove the duplicate line in `docs/roadmap-status.md`.
- Record the v2.9.7 slice in roadmap, status, changelog, and version metadata.

## Impact

- Remaining public docs now describe the same maintenance CLI truth.
- Telemetry collateral no longer under-reports the supported CLI surface.
- The status doc stays clean and auditable.
