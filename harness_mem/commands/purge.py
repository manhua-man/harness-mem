"""Purge command implementation."""

from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def cmd_purge(
    before_date: str,
    category: str,
    dry_run: bool,
    project_name: str | None = None,
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
            if entries_to_delete:
                if dry_run:
                    print(
                        f"[DRY RUN] Would soft-delete {len(entries_to_delete)} structured memories "
                        f"before {before_date} for project '{resolved_project}'"
                    )
                    for entry in entries_to_delete[:10]:
                        preview = entry.content[:80].replace("\n", " ")
                        print(f"  - {entry.id} [{entry.category}] {preview}...")
                    if len(entries_to_delete) > 10:
                        print(f"  ... and {len(entries_to_delete) - 10} more")
                else:
                    for entry in entries_to_delete:
                        await backend.structured_store.soft_delete_memory_entry(entry.id)
                    total_deleted += len(entries_to_delete)
                    structured_deleted = len(entries_to_delete)
                    print(f"Soft-deleted {len(entries_to_delete)} structured memories.")

        if total_deleted == 0 and not (category in ("observations", "all") or category in ("structured", "all")):
            print("Nothing to purge. Try --category observations, --category structured, or --category all.")
        elif total_deleted == 0:
            print(f"No entries found before {before_date} in category '{category}'.")

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
                },
            )
        elif dry_run:
            log_command_invoked(
                "purge",
                project_name=resolved_project,
                extra={"category": category, "before_date": before_date, "dry_run": True},
            )
        return 0
    finally:
        await backend.close()
