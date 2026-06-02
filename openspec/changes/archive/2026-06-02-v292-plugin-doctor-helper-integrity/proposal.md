## Why

The repo-local plugin currently ships `plugins/harness-mem/scripts/doctor.ps1`
as a validation helper, and plugin docs point users at it. But the script calls
`python -m harness_mem.cli status` even though `status` is intentionally not a
registered CLI subcommand in the maintenance-only CLI surface.

That means the helper finishes with a visible CLI error in real use, even when
the actual doctor pass succeeded. The plugin wrapper is therefore out of sync
with the current CLI contract.

## What Changes

- Make `doctor.ps1` invoke only supported maintenance commands.
- Preserve the optional `-Wake` user story as a hint surface instead of a
  removed CLI invocation.
- Add a real script-level smoke test under an isolated `HOME/USERPROFILE`.
- Align plugin docs with the repaired helper behavior.

## Impact

- Repo-local validation no longer ends with a bogus `invalid choice: 'status'`
  failure.
- The plugin helper remains compatible with the maintenance-only CLI contract.
- Users get a deterministic hint toward `/hm:wake` without reintroducing a
  removed terminal surface.
