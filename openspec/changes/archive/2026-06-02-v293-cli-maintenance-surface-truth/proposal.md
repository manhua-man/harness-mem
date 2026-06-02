## Why

The live `harness-mem --help` surface already ships `config` and `integration`
as top-level maintenance commands, and tests assert that this is the current
truth. But the main `openspec/specs/cli/spec.md` still claims the CLI surface
ends at `maintenance`, so the contract is stale relative to the shipped parser.

That mismatch makes the current CLI truth harder to audit and weakens the
maintenance-only boundary, because the real console exposes more than the main
spec admits.

## What Changes

- Update the top-level CLI surface contract to include `config` and
  `integration`.
- Add explicit requirements for config management and IDE hook installation as
  maintenance-only namespaces.
- Sync roadmap, changelog, and version metadata for the v2.9.3 truth-fix
  release.

## Impact

- OpenSpec matches the shipped `--help` output again.
- `config` / `integration` stay visible as supported maintenance commands
  without reopening removed daily-memory CLI verbs.
- Release and roadmap docs reflect the actual v2.9 maintenance surface.
