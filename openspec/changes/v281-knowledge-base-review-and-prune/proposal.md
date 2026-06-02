## Why

v2.8.0 formalizes session closure and manifest cleanup, but the knowledge-base
maintenance half of the workflow is still only partially specified. The repo
already exposes `/hm:review-kb` and `/hm:prune-kb` as user-facing entries and
implements them in the `session-distill` script, yet the runtime contract for
status classification, review baselines, backup-first cleanup, and next-step
guidance is not anchored in the main OpenSpec surface.

Without that contract, the script, slash docs, and health hints can drift apart:

- the meaning of `stable / needs-review / stale / superseded` is not yet a main
  workflow guarantee;
- prune safety depends on implementation convention rather than a formal backup
  and confinement promise;
- reminder summaries can drift from doctor-style next-step guidance.

v2.8.1 should formalize the knowledge-base review and prune surfaces before the
project extends reminder or verification behavior further.

## What Changes

- Add a formal workflow contract for `/hm:review-kb --next <n>`.
- Add a formal cleanup contract for `/hm:prune-kb --statuses stale,superseded`.
- Define baseline state and backup-first behavior for knowledge-base review and
  cleanup.
- Keep these surfaces slash-first and script-second, matching the daily-workflow
  contract.

## Impact

- Knowledge-base audit becomes a versioned maintenance behavior.
- Future verify-entry and reminder work can reuse one review-state model.
- Cleanup remains explicit, review-gated, and confined away from canonical
  truth.
