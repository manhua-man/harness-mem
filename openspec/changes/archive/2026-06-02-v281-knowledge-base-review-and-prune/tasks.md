## 1. Review-kb contract

- [x] 1.1 Formalize `/hm:review-kb --next <n>` as the user-facing knowledge-base audit entry.
- [x] 1.2 Define the `stable / needs-review / stale / superseded` status model.
- [x] 1.3 Define the persisted review baseline state (`reviewed_at`, entry count, summary).

## 2. Prune-kb contract

- [x] 2.1 Formalize `/hm:prune-kb --statuses stale,superseded` as backup-first cleanup.
- [x] 2.2 Explicitly confine cleanup to stale/superseded knowledge entries.
- [x] 2.3 Explicitly forbid prune-kb from mutating confirmed truth or unrelated maintenance artifacts.

## 3. Documentation alignment

- [x] 3.1 Update `docs/roadmap-v28.md` current status for the v2.8.1 slice.
- [x] 3.2 Keep the slash-first, script-second boundary explicit for review-kb/prune-kb.

## 4. Validation

- [x] 4.1 `openspec validate --all --strict`
