## Why

The shipped host-trigger path has long been `python -m harness_mem.host_entry`
with required flags such as `--project-root` and `--source`. Hook templates,
operator docs, runtime code, and tests all agree on that. But `roadmap-v24`
still carried a placeholder package path, an older `harness_mem.host` module
name, and an invocation form that incorrectly treated `reflection_once` as a
positional host-entry subcommand.

## What Changes

- Update the remaining v2.4 roadmap wording to use the shipped
  `python -m harness_mem.host_entry` module path and flag-based invocation.
- Remove placeholder and stale forms such as `harness_mem.<host_entry>`,
  `python -m harness_mem.host`, and `host_entry reflection_once`.
- Add a focused regression test that fails fast if current-truth docs drift back
  to those older invocation forms.

## Impact

- Current docs stop teaching host-entry commands the shipped runtime does not
  accept.
- Future doc edits that reintroduce placeholder or stale host-entry invocation
  forms fail fast in CI.
