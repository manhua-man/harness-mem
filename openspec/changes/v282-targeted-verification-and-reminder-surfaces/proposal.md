## Why

v2.8.0 formalizes session closure and manifest cleanup, and v2.8.1 formalizes
knowledge-base review and prune. The remaining maintenance surface is targeted
recheck and reminder behavior: `/hm:verify-entry`, reminder thresholds after
marking or packet generation, and the boundary that these prompts remain
summary-only nudges instead of automatic cleanup or truth mutation.

Those behaviors already exist in the repo-local session-distill tooling, but
they are still governed mostly by implementation convention and prompt docs. A
formal contract is needed so future changes do not silently turn reminders into
hard gates or implicit cleanup.

## What Changes

- Add a formal workflow contract for `/hm:verify-entry <session-id|keyword>`.
- Add a formal contract for knowledge-overlap and review-baseline reminder
  thresholds.
- Keep reminders summary-only: they may suggest `/hm:review-kb` or
  `/hm:verify-entry`, but must not auto-prune, auto-supersede, or block the
  main distill flow.

## Impact

- Targeted verification becomes a versioned user-facing maintenance behavior.
- Reminder logic becomes explicit and testable.
- The maintenance family stays advisory-first rather than turning into a hidden
  autonomous cleanup system.
