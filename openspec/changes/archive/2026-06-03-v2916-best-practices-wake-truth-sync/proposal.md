## Why

The shipped runtime already exposes `wake` as a first-class MCP read surface,
with `renderer="compact"` and `include_skill_hints=true` as explicit opt-in
extensions. But `docs/best-practices.md` still described wake-up in abstract
terms and did not list `wake` in its runtime tool catalog.

That leaves a gap between the documentation aimed at agent authors and the
surface the runtime actually wants them to call.

## What Changes

- Add `wake` to the best-practices runtime tool catalog.
- Rewrite the wake-up section so it explicitly names
  `wake(project_name=<project>)` as the default surface.
- Document compact/generated wake and skill hints as explicit opt-ins.
- Add a focused regression test that fails fast if `best-practices` drifts back
  to the older abstract wording.

## Impact

- Agent-author guidance now matches the shipped wake surface more directly.
- Future doc edits that remove `wake` from the tool catalog or blur the default
  wake surface fail fast in CI.
