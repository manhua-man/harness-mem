"""Commands for managing task handoffs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from harness_mem.commands import support as command_support
from harness_mem.core.schemas import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

HANDOFF_STATUSES = ("in_progress", "pending", "blocked", "done")

async def cmd_handoff(
    project_name: str, 
    task_id: str, 
    summary: str, 
    status: str = "in_progress", 
    next_steps: list[str] | None = None, 
    blockers: list[str] | None = None
) -> int:
    """Create or update a task handoff."""
    clean_status = command_support.normalize_handoff_status(status)
    clean_next_steps = command_support.clean_cli_list(next_steps)
    clean_blockers = command_support.clean_cli_list(blockers)
    
    if clean_status not in HANDOFF_STATUSES:
        allowed = ", ".join(HANDOFF_STATUSES)
        print(f"Invalid handoff status: {status}. Expected one of: {allowed}")
        return 1

    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Check if task already exists
        existing = None
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=100)
        for h in handoffs:
            if h.task_id == task_id:
                existing = h
                break

        if existing:
            # Update
            now = datetime.now(timezone.utc)
            existing.summary = summary
            existing.status = clean_status
            if clean_next_steps:
                existing.next_steps = clean_next_steps
            if clean_blockers:
                existing.blockers = clean_blockers
            existing.last_activity = now
            existing.updated_at = now
            await backend.structured_store.save_task_handoff(existing)
            print(f"Updated handoff: {existing.id}")
        else:
            handoff = TaskHandoff(
                id=str(uuid4()),
                project_name=project_name,
                task_id=task_id,
                summary=summary,
                status=clean_status,
                next_steps=clean_next_steps,
                blockers=clean_blockers,
            )
            await backend.structured_store.save_task_handoff(handoff)
            print(f"Created handoff: {handoff.id}")

        return 0
    finally:
        await backend.close()
