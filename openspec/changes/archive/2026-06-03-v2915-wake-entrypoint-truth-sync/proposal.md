## Why

The shipped runtime already has a first-class MCP `wake` tool, and later
versions layered compact generated summaries and opt-in skill hints onto that
same surface. But the repo-local `/hm:wake` command doc and the `harness-mem`
skill still taught a planning-era manual choreography of
`get_project_profile` + `get_task_handoffs` + `get_confirmed_rules` +
`timeline`.

That is no longer the best current-truth guidance for users or agents. It
pushes them toward an older composition path instead of the shipped wake
surface the runtime actually optimizes and tests.

## What Changes

- Update `/hm:wake` guidance to call MCP `wake(project_name=<project>)` by
  default.
- Document `renderer="compact"` and `include_skill_hints=true` as explicit
  opt-in wake extensions.
- Update the repo-local `harness-mem` skill so its status/wake flow uses
  `get_project_status` + `wake(...)` rather than manual low-level reads.
- Add a focused regression test that fails fast if these docs drift back to the
  older manual wake choreography.

## Impact

- Repo-local wake guidance now matches the shipped runtime surface users should
  prefer.
- Future doc edits that reintroduce the older low-level wake choreography fail
  fast in CI.
