# Output Layout

The script writes its working files to the distillation workspace, which defaults to:

`C:\Users\EDY\.codex\session-distill`

## Files

- `manifest.json`: source of truth for discovered sessions and their statuses.
- `knowledge-base.md`: curated shared knowledge promoted from multiple sessions.
- `packets/<session-id>.md`: compact review packet generated from a raw `.jsonl` archive.
- `distilled/sessions/<session-id>.md`: human-written session note after reviewing a packet.
- `pruned-sources.jsonl`: audit log for raw source archives deleted through the `prune` command.

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
6. Mark the session as `distilled` or `skipped`.

## Cleanup

- Use `prune --delete-packets` to remove regenerated packet files.
- Use `prune --delete-source` only for sessions that are truly absorbed, typically `status=distilled`.
- Keep `knowledge-base.md` and `manifest.json`.
- When `--delete-source` is used, the script appends a record to `pruned-sources.jsonl` before deleting the raw archive.
