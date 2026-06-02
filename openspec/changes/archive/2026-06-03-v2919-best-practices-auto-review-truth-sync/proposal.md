## Why

The shipped runtime already exposes
`auto_review_candidates(project_name=<project>, apply=true)` as the default
low-risk review surface for distill. But `docs/best-practices.md` still taught
an older per-item pattern centered on `list_candidates` plus direct
`confirm_*` / `reject_*` actions as if that were the normal distill path.

That leaves the agent-author guidance in `best-practices` out of sync with the
review surface the runtime actually wants `/hm:distill` to call.

## What Changes

- Update the Memory Expert and Gardener guidance to center the shipped
  `auto_review_candidates` surface.
- Update the runtime tool table so `auto_review_candidates` is the default
  distill/review management tool and `list_candidates` becomes explicit
  drilldown/recheck tooling.
- Add a focused regression test that fails fast if `best-practices` drifts back
  to the older per-item review wording.

## Impact

- Best-practices guidance now matches the shipped auto-review surface more
  directly.
- Future doc edits that reintroduce `list_candidates` as the default distill
  review path fail fast in CI.
