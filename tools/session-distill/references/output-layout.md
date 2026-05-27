# Output Layout

The script writes its working files to the distillation workspace, which defaults to:

`%USERPROFILE%\.codex\session-distill`

## Files

- `manifest.json`: source of truth for discovered sessions and their statuses.
- `knowledge-base.md`: curated shared knowledge promoted from multiple sessions.
- `packets/<session-id>.md`: compact review packet generated from a raw `.jsonl` archive.
- `distilled/sessions/<session-id>.md`: human-written session note after reviewing a packet.
- `pruned-sources.jsonl`: legacy audit log for raw source archives deleted by explicit maintenance.
- `memory-drafts/<session-id>.json`: structured draft entries that must be resolved before `/hm:mark ... distilled`.
- `kb-review-state.json`: last `/hm:review-kb` timestamp, entry count, and status summary.
- `backups/knowledge-base/`: automatic backups written before `/hm:prune-kb` mutates `knowledge-base.md`.

## Statuses

- `new`: indexed but not yet packetized.
- `bundled`: packet generated and ready for review.
- `distilled`: session note is written, stable knowledge is promoted, and the repo-local project-rule decision is complete.
- `skipped`: intentionally left out of the active queue.

## Recommended Loop

1. Run `distill-next.ps1` or `archived_session_distiller.py bundle --next 1`.
2. Read the new packet.
3. Update `distilled/sessions/<session-id>.md`.
4. Promote stable items into `knowledge-base.md`.
5. Decide whether any promoted lesson should also update repo-local guidance (`AGENTS.md`, `CLAUDE.md`, `.kiro/steering/*.md`).
6. Use `/hm:mark <session-id> distilled` or `/hm:mark <session-id> skipped`.

## Slash Maintenance Entries

- `/hm:mark <session-id> distilled [--keep-raw]`: run the session-note, raw-review, promotion, memory-draft, and knowledge-base guardrails before closing a session.
- `/hm:prune --statuses distilled,skipped --source-missing`: remove manifest placeholders whose raw source has already gone missing.
- `/hm:review-kb --next 20`: classify knowledge-base entries as stable / needs-review / stale / superseded.
- `/hm:prune-kb --statuses stale,superseded`: back up and remove stale or superseded knowledge entries.
- `/hm:verify-entry <session-id|keyword>`: pull matching knowledge entries and grill-style recheck questions.

## Cleanup

Cleanup is a developer maintenance concern, not part of the user-facing distill flow.
Keep `knowledge-base.md` and `manifest.json`; only remove raw source archives after an explicit cleanup request.
