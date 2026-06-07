# Acceptance Checklist: `maintenance_recovery`

Use this checklist before accepting any MR1-MR5 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `maintenance_recovery`.
- [ ] `condition` is `recovery`.
- [ ] Input broken/stale state is described.
- [ ] Command or tool transcript exists.
- [ ] Before/after state exists when recovery is claimed.
- [ ] False success is counted as failure.
- [ ] Guidance stays within maintenance/troubleshooting surfaces.

## MR1: Doctor Diagnosis

Pass requires all of:

- [ ] Doctor or health output detects the seeded issue.
- [ ] Message is actionable.
- [ ] Issue-specific evidence is visible.

Primary failure signals:

- Generic OK is reported for a broken state.

## MR2: Rebuild Vector Index

Pass requires all of:

- [ ] Missing or stale vector index is detected.
- [ ] Rebuild action is recorded.
- [ ] After state proves recovery or reports failure.

Primary failure signals:

- Rebuild reports success without after-state evidence.

## MR3: Vector Mismatch Detection

Pass requires all of:

- [ ] Mismatch is detected.
- [ ] Expected and actual state are named.
- [ ] Recovery or next action is clear.

Primary failure signals:

- Mismatch is hidden as a normal empty result.

## MR4: Missing Cache or Transport

Pass requires all of:

- [ ] Missing cache or transport problem is diagnosed.
- [ ] User-facing guidance is current.
- [ ] Obsolete daily CLI fallback is absent.

Primary failure signals:

- User is told to use removed wake/search/timeline daily commands.

## MR5: False Success Recovery Guard

Pass requires all of:

- [ ] Deliberately unrecovered state is not reported as recovered.
- [ ] False-success count is recorded.
- [ ] Missing proof is named.

Primary failure signals:

- Success text alone is accepted as recovery proof.
