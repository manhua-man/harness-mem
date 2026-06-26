# Output Layout

The script writes its working files to the distillation workspace, which defaults to:

`%USERPROFILE%\.codex\session-distill`

## Files

- `manifest.json`: source of truth for discovered sessions and their statuses.
- `packets/<session-id>.md`: compact review packet generated from a raw `.jsonl` archive.
- `distilled/sessions/<session-id>.md`: human-written session note after reviewing a packet.
- `pruned-sources.jsonl`: legacy audit log for raw source archives deleted by explicit maintenance.
- `memory-drafts/<session-id>.json`: structured draft entries that must be resolved before `/hm:mark ... distilled`.

## Statuses

- `new`: indexed but not yet packetized.
- `bundled`: packet generated and ready for review.
- `distilled`: session note is written and any candidate export / review decision is complete.
- `skipped`: intentionally left out of the active queue.

## Recommended Loop

1. Run `distill-next.ps1` or `archived_session_distiller.py bundle --next 1`.
2. Read the new packet.
3. Extract candidate drafts from supported evidence.
4. Export candidates through harness-mem `suggest_*` tools.
5. Review durable memory through `/hm:review`.
6. Optionally update `distilled/sessions/<session-id>.md` when preserving archive context is useful.
7. Use `/hm:mark <session-id> distilled` or `/hm:mark <session-id> skipped`.

## Slash Maintenance Entries

- `/hm:mark <session-id> distilled [--keep-raw]`: run the session-note, raw-review, and memory-draft guardrails before closing a session.
- `/hm:prune --statuses distilled,skipped --source-missing`: remove manifest placeholders whose raw source has already gone missing.

## Cleanup

Cleanup is a developer maintenance concern, not part of the user-facing distill flow.
Keep `manifest.json`; only remove raw source archives after an explicit cleanup request.
Session-distill does not maintain an independent KB or PRD layer. Durable knowledge goes through harness-mem candidates and `/hm:review`.
