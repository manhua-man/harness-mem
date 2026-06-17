# Acceptance Checklist: `context_outcome_loop`

Use this checklist before judging any COL1-COL5 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `context_outcome_loop`.
- [ ] The run uses isolated temporary storage, not a real user data directory.
- [ ] `record_context_outcome` writes only `RetrievalSignal` records.
- [ ] Confirmed memory entry and rule counts are unchanged after outcome recording.
- [ ] Ranking influence is enabled only when `weak_link_signals=True`.
- [ ] Search or wake output includes explanation metadata when outcome influence is visible.
- [ ] The report states that this is not a broad answer-quality, token-saving, or default-ranking claim.

## COL1: Used Outcome Signal

Pass requires all of:

- [ ] A `used` outcome is recorded for an existing surfaced source id.
- [ ] The source receives a positive bounded `context_outcome_score`.
- [ ] The result metadata explains the positive hint.

Primary failure signals:

- A `used` outcome mutates confirmed truth.
- A positive hint appears while `weak_link_signals=False`.

## COL2: Ignored Outcome Signal

Pass requires all of:

- [ ] An `ignored` outcome is recorded for an existing surfaced source id.
- [ ] The source receives a small bounded negative or neutral hint.
- [ ] The result metadata preserves the outcome count.

Primary failure signals:

- Ignored signals silently delete or archive truth.

## COL3: Misleading Outcome Signal

Pass requires all of:

- [ ] A `misleading` outcome is recorded for an existing surfaced source id.
- [ ] The source receives a stronger bounded negative hint than `ignored`.
- [ ] The response can explain why the hint was applied.

Primary failure signals:

- Misleading signals become irreversible truth decay or hidden deletion.

## COL4: Disabled Influence

Pass requires all of:

- [ ] With `weak_link_signals=False`, search ranking does not apply outcome hints.
- [ ] Response metadata does not imply outcome influence was used.
- [ ] Stored signals remain available for later opt-in use.

Primary failure signals:

- Outcome ranking affects default search.

## COL5: Write Failure Isolation

Pass requires all of:

- [ ] Failed signal writes are reported as failures.
- [ ] Search and wake remain usable after signal write failure.
- [ ] No partial failure mutates confirmed truth.

Primary failure signals:

- Signal write failure blocks ordinary retrieval.
- Failure is reported as success.
