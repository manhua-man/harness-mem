## Why

The shipped runtime already exposes `auto_review_candidates(apply=true)` as the
shared low-risk review surface for distill. But the repo-local `/hm:distill`
command doc, the `harness-mem` skill, and one MCP spec example still taught an
older per-item pattern built around `list_candidates` plus manual
`confirm_*` / `reject_*` calls.

That leaves agent-author guidance out of sync with the review surface the
runtime actually wants `/hm:distill` to call.

## What Changes

- Update `/hm:distill` command guidance to use
  `auto_review_candidates(project_name=<project>, apply=true)` as the default
  review surface.
- Update the repo-local `harness-mem` skill to remove the stale
  "when available" fallback wording.
- Update the MCP distill example so it shows `auto_review_candidates` summary
  fields and `applied_decisions`.
- Add a focused regression test that fails fast if these user-facing surfaces
  drift back to manual per-item review wording.

## Impact

- Distill guidance now matches the shipped shared auto-review surface.
- Future doc/skill edits that reintroduce manual `list_candidates` +
  `confirm_*` / `reject_*` as the default distill path fail fast in CI.
