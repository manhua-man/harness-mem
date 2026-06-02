## 1. Review-kb contract

- [ ] 1.1 Formalize `/hm:review-kb --next <n>` as the user-facing knowledge-base audit entry.
- [ ] 1.2 Define the `stable / needs-review / stale / superseded` status model.
- [ ] 1.3 Define the persisted review baseline state (`reviewed_at`, entry count, summary).

## 2. Prune-kb contract

- [ ] 2.1 Formalize `/hm:prune-kb --statuses stale,superseded` as backup-first cleanup.
- [ ] 2.2 Explicitly confine cleanup to stale/superseded knowledge entries.
- [ ] 2.3 Explicitly forbid prune-kb from mutating confirmed truth or unrelated maintenance artifacts.

## 3. Documentation alignment

- [ ] 3.1 Update `docs/roadmap-v28.md` current status for the v2.8.1 slice.
- [ ] 3.2 Keep the slash-first, script-second boundary explicit for review-kb/prune-kb.

## 4. Validation

- [ ] 4.1 `openspec validate --all --strict`
