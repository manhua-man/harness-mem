## Why

The shipped runtime already exposes `get_project_status(project_name=<project>)`
as the primary project-memory triage surface, including `phase`,
`suggested_slash`, `reason`, and optional repair hints. But the repo-local
`/hm:status` command doc still taught an older manual assembly pattern built
around `get_project_profile`, `list_candidates`, and `timeline`, and the MCP
spec example still showed only a partial status payload.

That leaves agent-author guidance out of sync with the triage surface the
runtime actually wants `/hm:status` to call.

## What Changes

- Update `/hm:status` command guidance to use
  `get_project_status(project_name=<project>)` as the default triage surface.
- Update the MCP status example so it shows `phase`, `suggested_slash`,
  `reason`, and repair hints directly.
- Add a daily-workflow requirement that guards `/hm:status` against drifting
  back to manual low-level read assembly.
- Add a focused regression test that fails fast if these user-facing surfaces
  drift back.

## Impact

- Status guidance now matches the shipped triage surface more directly.
- Future doc/spec edits that reintroduce manual status assembly fail fast in CI.
