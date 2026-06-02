## 1. Verify-entry contract

- [x] 1.1 Formalize `/hm:verify-entry <session-id|keyword>` as a user-facing targeted recheck entry.
- [x] 1.2 Define the grill-style recheck output and matching behavior.

## 2. Reminder surfaces

- [x] 2.1 Formalize review-baseline reminders after mark when KB growth reaches the configured threshold.
- [x] 2.2 Formalize overlap reminders after packet generation or session-note marking.
- [x] 2.3 Keep reminders summary-only and non-blocking.

## 3. Documentation alignment

- [x] 3.1 Update `docs/roadmap-v28.md` current status for the v2.8.2 slice.
- [x] 3.2 Keep the slash-first, script-second boundary explicit for verify-entry and reminders.

## 4. Validation

- [x] 4.1 `openspec validate --all --strict`
