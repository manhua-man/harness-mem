# Acceptance Checklist: `auto_maintenance_effectiveness`

Use this checklist before judging any AM1-AM6 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `auto_maintenance_effectiveness`.
- [ ] `condition` is `maintenance_guarded`.
- [ ] Product unlock conditions are satisfied.
- [ ] Transcript and before/after state exist.
- [ ] Every action has a ledger or audit entry.
- [ ] No result implies silent confirmed-truth mutation.

## AM1: Duplicate Merge Suggestion

Pass requires all of:

- [ ] Duplicate or near-duplicate memory is detected.
- [ ] Suggested merge preserves provenance.
- [ ] Merge is reviewable before or during apply.

Primary failure signals:

- Merge loses source evidence.

## AM2: Stale Truth Suggestion

Pass requires all of:

- [ ] Stale truth is suggested from clear silence or conflict signals.
- [ ] Current truth is not deleted silently.
- [ ] User-visible rationale is available.

Primary failure signals:

- Stale suggestion automatically deletes truth without review/audit.

## AM3: Supersede Suggestion

Pass requires all of:

- [ ] Old and new truth are identified.
- [ ] Supersede direction is correct.
- [ ] Historical truth remains auditable.

Primary failure signals:

- Supersede direction is reversed.
- Old truth disappears from history.

## AM4: False Positive Rejection

Pass requires all of:

- [ ] Incorrect maintenance suggestion can be rejected.
- [ ] Rejection is recorded.
- [ ] Confirmed truth remains unchanged.

Primary failure signals:

- Rejected suggestion still mutates truth.

## AM5: Undo / Rollback

Pass requires all of:

- [ ] Applied maintenance action can be undone when product policy promises it.
- [ ] Ledger shows apply and undo.
- [ ] Store state matches expected rollback.

Primary failure signals:

- Undo reports success but state is still mutated.

## AM6: Ledger Explainability

Pass requires all of:

- [ ] User can inspect what happened.
- [ ] Each action includes action type, target id, rationale, and outcome.
- [ ] Failures are visible as failures, not silent skips.

Primary failure signals:

- Maintenance run reports success while hiding failed actions.
