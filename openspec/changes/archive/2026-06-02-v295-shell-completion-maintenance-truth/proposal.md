## Why

`harness-mem` already ships a `--completion` surface, but its generated shell
scripts still reflect the pre-v2.9 maintenance console: they omit `config` and
`integration`, and zsh omits the `qs` alias entirely.

That means shell completion is now the last user-facing CLI surface still
teaching an outdated command set, even though `--help`, tests, and the main
CLI spec were already updated.

## What Changes

- Update bash, zsh, and fish completion output to include the current
  maintenance command set.
- Add completion coverage for `config` / `integration` actions.
- Add focused tests and record the slice in release docs.

## Impact

- `harness-mem --completion <shell>` now matches the real maintenance console.
- Users do not get stale command suggestions from shell completion.
- The completion surface is covered by tests rather than relying on manual
  inspection.
