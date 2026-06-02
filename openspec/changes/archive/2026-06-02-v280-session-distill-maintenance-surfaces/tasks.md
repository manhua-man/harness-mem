## 1. Session closure contract

- [x] 1.1 Formalize `/hm:mark <session-id> distilled [--keep-raw]` as a user-facing maintenance entry in the main workflow spec.
- [x] 1.2 Define the required session note / raw review / promotion / draft / knowledge-base guardrails before `distilled` is accepted.
- [x] 1.3 Define the allowed raw-deletion boundary and the `--keep-raw` bypass.

## 2. Manifest cleanup contract

- [x] 2.1 Define the manifest status model for handled sessions, including `distilled`, `skipped`, `source_missing`, and `raw_deleted_at`.
- [x] 2.2 Define `/hm:prune --statuses distilled,skipped --source-missing` as cleanup for handled placeholders only.
- [x] 2.3 Explicitly forbid cleanup from mutating confirmed truth or unrelated raw session assets.

## 3. Documentation alignment

- [x] 3.1 Add `docs/roadmap-v28.md` describing the v2.8 maintenance family.
- [x] 3.2 Update documentation indexes so v2.8 appears in the roadmap list.
- [x] 3.3 Record the slash-first, script-second boundary for these maintenance entries.

## 4. Validation

- [x] 4.1 `openspec validate --all --strict`
