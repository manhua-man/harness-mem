"""Purge command implementation."""

from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.data_lifecycle import hard_delete


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _quality_label(entry: object) -> str:
    """Classify a memory entry by usage recency."""
    usage = getattr(entry, "usage_count", 0) or 0
    last_acc = getattr(entry, "last_accessed_at", None)
    if usage == 0:
        return "never-accessed"
    if last_acc is None:
        return "stale"
    return "active"


async def cmd_purge(
    before_date: str,
    category: str,
    dry_run: bool,
    project_name: str | None = None,
    *,
    stale_only: bool = False,
) -> int:
    """Soft-delete observations/structured memory before a given date."""
    try:
        cutoff = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Invalid date format: {before_date}. Use YYYY-MM-DD.")
        return 1

    resolved_project = resolve_project_name(
        project_name,
        required=category == "structured" or category == "all",
        action_label="purge",
    )
    if category in ("structured", "all") and not resolved_project:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        total_deleted = 0
        total_matched = 0
        observations_deleted = 0
        structured_deleted = 0

        if category in ("observations", "all"):
            all_obs = await backend.verbatim_store.list(limit=100000)
            to_delete = [
                observation
                for observation in all_obs
                if observation.timestamp
                and _as_utc(observation.timestamp) < cutoff
                and (
                    resolved_project is None
                    or observation.metadata.get("project_name") == resolved_project
                )
            ]
            if to_delete:
                total_matched += len(to_delete)
                if dry_run:
                    target_scope = f" for project '{resolved_project}'" if resolved_project else ""
                    print(
                        f"[DRY RUN] Would soft-delete {len(to_delete)} observations "
                        f"before {before_date}{target_scope}"
                    )
                    for observation in to_delete[:10]:
                        ts = observation.timestamp.strftime("%Y-%m-%d") if observation.timestamp else "?"
                        preview = observation.raw_content[:80].replace("\n", " ")
                        print(f"  - {observation.id} [{ts}] {preview}...")
                    if len(to_delete) > 10:
                        print(f"  ... and {len(to_delete) - 10} more")
                else:
                    for observation in to_delete:
                        await backend.verbatim_store.soft_delete(observation.id)
                    total_deleted += len(to_delete)
                    observations_deleted = len(to_delete)
                    print(f"Soft-deleted {len(to_delete)} observations.")

        if category in ("structured", "all"):
            assert resolved_project is not None
            entries = await backend.structured_store.list_memory_entries(resolved_project, limit=100000)
            entries_to_delete = [
                entry for entry in entries
                if entry.created_at and _as_utc(entry.created_at) < cutoff
            ]

            if stale_only:
                entries_to_delete = [
                    e for e in entries_to_delete
                    if _quality_label(e) in ("never-accessed", "stale")
                ]

            if entries_to_delete:
                total_matched += len(entries_to_delete)
                if dry_run:
                    stale_note = " (stale only)" if stale_only else ""
                    print(
                        f"[DRY RUN] Would soft-delete {len(entries_to_delete)} structured memories "
                        f"before {before_date} for project '{resolved_project}'{stale_note}"
                    )
                    for entry in entries_to_delete[:10]:
                        preview = entry.content[:60].replace("\n", " ")
                        quality = _quality_label(entry)
                        usage = getattr(entry, "usage_count", 0) or 0
                        last_acc = getattr(entry, "last_accessed_at", None)
                        acc_str = last_acc.strftime("%Y-%m-%d") if last_acc else "never"
                        print(f"  - {entry.id} [{entry.category}] uses={usage} last={acc_str} ({quality}) {preview}...")
                    if len(entries_to_delete) > 10:
                        print(f"  ... and {len(entries_to_delete) - 10} more")
                else:
                    for entry in entries_to_delete:
                        await backend.structured_store.soft_delete_memory_entry(entry.id)
                    total_deleted += len(entries_to_delete)
                    structured_deleted = len(entries_to_delete)
                    print(f"Soft-deleted {len(entries_to_delete)} structured memories.")

        if total_matched == 0 and not (category in ("observations", "all") or category in ("structured", "all")):
            print("Nothing to purge. Try --category observations, --category structured, or --category all.")
        elif total_matched == 0:
            scope = "stale " if stale_only else ""
            print(f"No {scope}entries found before {before_date} in category '{category}'.")

        if not dry_run and total_deleted > 0:
            print("Run 'harness-mem doctor' to check new memory budget.")
            log_command_invoked(
                "purge",
                project_name=resolved_project,
                extra={
                    "category": category,
                    "before_date": before_date,
                    "observations_deleted": observations_deleted,
                    "structured_deleted": structured_deleted,
                    "stale_only": stale_only,
                },
            )
        elif dry_run:
            log_command_invoked(
                "purge",
                project_name=resolved_project,
                extra={"category": category, "before_date": before_date, "dry_run": True, "stale_only": stale_only},
            )
        return 0
    finally:
        await backend.close()


async def cmd_erase(
    project_name: str,
    *,
    session_id: str | None = None,
    source_id: str | None = None,
    before_date: str | None = None,
    apply: bool = False,
    reason: str = "user_requested_erasure",
) -> int:
    """Preview or execute irreversible transcript and derived-data erasure."""

    if not any((session_id, source_id, before_date)):
        print("Refusing project-wide erasure without --session-id, --source-id, or --before.")
        return 1
    cutoff = None
    if before_date:
        try:
            cutoff = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Invalid date format: {before_date}. Use YYYY-MM-DD.")
            return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        result = await hard_delete(
            backend,
            project_name=project_name,
            session_id=session_id,
            source_id=source_id,
            before=cutoff,
            reason=reason,
            apply=apply,
        )
        plan = result["plan"]
        prefix = "ERASED" if apply else "DRY RUN"
        print(f"[{prefix}] project={project_name}")
        print(
            "  revisions={revisions} chunks={chunks} observations={observations} "
            "candidates={candidates} structured_truth={structured_truth} raw_bytes={raw_bytes}".format(
                **plan["counts"]
            )
        )
        if apply:
            print(f"  audit_id={result['audit']['id']}")
        else:
            print("No data changed. Re-run with --apply to execute irreversible erasure.")
        return 0
    finally:
        await backend.close()


__all__ = ["cmd_erase", "cmd_purge"]
