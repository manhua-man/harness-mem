## Why

The shipped runtime already uses
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface. But `tools/session-distill/SKILL.md` still described an
older chain centered on `list_candidates` plus low-risk confirm/reject, and the
plugin README's `/hm:distill` summary row still used a looser "auto-judge"
description.

That leaves the repo-local distill playbook out of sync with the review surface
the runtime actually wants `/hm:distill` and the `session-distill` skill to
call.

## What Changes

- Update `tools/session-distill/SKILL.md` so its default review surface is
  `auto_review_candidates(project_name=<project>, apply=true)`.
- Keep `list_candidates` and `confirm_*` / `reject_*` as explicit drilldown or
  repair tools rather than the default distill path.
- Update the plugin README's `/hm:distill` summary row to mention
  `auto_review_candidates` directly.
- Add a focused regression test that fails fast if these docs drift back to the
  older `list_candidates -> confirm/reject` mainline.

## Impact

- The repo-local distill playbook now matches the shipped auto-review surface
  more directly.
- Future doc edits that reintroduce the older manual-review mainline fail fast
  in CI.
