"""Memory-entry and task-handoff persistence for LocalStructuredStore."""

# The concrete LocalStructuredStore supplies persistence primitives and sibling
# capability methods through composition. Contract tests exercise the complete host.
# mypy: disable-error-code="attr-defined"

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from typing import Any

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.governance_status import (
    GOVERNANCE_STATUSES,
    READABLE_TRUTH_FILTER,
    statuses_for_list_filter,
    validate_status_transition,
)
from harness_mem.storage.structured_store_support import (
    _copy_search_score_fields,
)


class StructuredMemoryMixin:
    async def save_memory_entry(self, entry: MemoryEntry) -> str:
        blob_path = self._blob_path("memory_entries", entry.id)
        blob_path.write_text(json.dumps(entry.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.upsert,
            "memory_entries",
            {
                "id": entry.id,
                "project_name": entry.project_name,
                "category": entry.category,
                "content": entry.content,
                "confidence": entry.confidence,
                "status": entry.status,
                "source": entry.source,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "tags": entry.tags,
                "compacted": entry.compacted,
                "usage_count": entry.usage_count,
                "last_accessed_at": entry.last_accessed_at,
                "memory_type": entry.memory_type,
                "valid_from": entry.valid_from,
                "valid_to": entry.valid_to,
                "recorded_at": entry.recorded_at,
                "supersedes": entry.supersedes,
                "superseded_by": entry.superseded_by,
            },
        )

        # Persist embedding vector (v1.6.2)
        try:
            from harness_mem.commands.support import get_embedding_model_id

            model_id = get_embedding_model_id()
            await asyncio.to_thread(
                self._index.persist_embedding,
                entry.id,
                entry.content,
                model_id,
            )
        except Exception:
            # Embedding persistence is best-effort, don't fail the save
            pass

        return entry.id

    async def get_memory_entry(self, id: str) -> MemoryEntry | None:
        blob_path = self._blob_path("memory_entries", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return MemoryEntry.from_dict(data)

    async def list_memory_entries(
        self,
        project_name: str,
        category: str | None = None,
        limit: int = 100,
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        deep_recall: bool = False,
        include_provisional: bool = False,
    ) -> list[MemoryEntry]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        where_parts = [
            "project_name = ?",
            "COALESCE(compacted, 0) = 0",
            f"COALESCE(status, 'pending') IN ({placeholders})",
        ]
        params: list[Any] = [project_name, *status_filter]
        if not include_history:
            clause, clause_params = self._current_only_clause()
            where_parts.append(clause)
            params.extend(clause_params)
        if category:
            where_parts.append("category = ?")
            params.append(category)
        where = " AND ".join(where_parts)
        rows = await asyncio.to_thread(
            self._index.list,
            "memory_entries",
            where,
            tuple(params),
            order_by="created_at DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("memory_entries", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                entry_status = data.get("status", "pending")
                if entry_status not in status_filter:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._tier_visible(data, deep_recall=deep_recall):
                    continue
                results.append(MemoryEntry.from_dict(data))
        return results

    async def search_memory_entries(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        mode: str = "auto",
        status: str = READABLE_TRUTH_FILTER,
        memory_type: list[str] | None = None,
        include_history: bool = False,
        deep_recall: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
        include_provisional: bool = False,
    ) -> list[MemoryEntry]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        extra_where_parts = [
            "COALESCE(compacted, 0) = 0",
            f"COALESCE(status, 'pending') IN ({placeholders})",
        ]
        extra_params: tuple = tuple(status_filter)
        if not include_history:
            clause, clause_params = self._current_only_clause()
            extra_where_parts.append(clause)
            extra_params = (*extra_params, *clause_params)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)
        if memory_type:
            placeholders = ",".join(["?"] * len(memory_type))
            extra_where_parts.append(
                f"COALESCE(memory_type, 'semantic') IN ({placeholders})"
            )
            extra_params = (*extra_params, *memory_type)
        window_clause, window_params = self._time_window_clause(time_window)
        if window_clause:
            extra_where_parts.append(window_clause)
            extra_params = (*extra_params, *window_params)
        search_result = await asyncio.to_thread(
            self._search.search,
            query,
            "memory_entries",
            limit,
            " AND ".join(extra_where_parts),
            extra_params,
            mode,
        )
        results = []
        for row in search_result.rows:
            blob_path = self._blob_path("memory_entries", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                if data.get("status", "pending") not in status_filter:
                    continue
                if (
                    memory_type
                    and data.get("memory_type", "semantic") not in memory_type
                ):
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._tier_visible(data, deep_recall=deep_recall):
                    continue
                if not self._truth_in_time_window(data, time_window):
                    continue
                data.update(
                    {
                        "_search_mode": search_result.effective_mode,
                        "_search_requested_mode": search_result.requested_mode,
                        "_search_fallback_reason": search_result.fallback_reason,
                    }
                )
                _copy_search_score_fields(data, row)
                results.append(MemoryEntry.from_dict(data))
        return results

    async def update_memory_entry_status(self, id: str, status: str) -> bool:
        """Update the governance status of a memory entry."""
        if status not in GOVERNANCE_STATUSES:
            return False
        blob_path = self._blob_path("memory_entries", id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
        current = data.get("status", "pending")
        if not validate_status_transition(current, status):
            return False
        data["status"] = status
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "memory_entries",
            id,
            {"status": status},
        )
        return True

    async def soft_delete_memory_entry(self, id: str) -> bool:
        """Soft-delete a memory entry by setting compacted=True."""
        blob_path = self._blob_path("memory_entries", id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
        data["compacted"] = True
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "memory_entries",
            id,
            {"compacted": True},
        )
        return True

    async def touch_memory_entry(
        self, id: str, accessed_at: datetime | None = None
    ) -> bool:
        """Record that a memory entry was surfaced."""
        blob_path = self._blob_path("memory_entries", id)
        if not blob_path.exists():
            return False

        touched_at = accessed_at or datetime.now(timezone.utc)
        data = json.loads(blob_path.read_text())
        usage_count = int(data.get("usage_count") or 0) + 1
        data["usage_count"] = usage_count
        data["last_accessed_at"] = touched_at.isoformat()
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "memory_entries",
            id,
            {
                "usage_count": usage_count,
                "last_accessed_at": touched_at,
            },
        )
        return True

    # ---- TaskHandoff ----

    async def save_task_handoff(self, handoff: TaskHandoff) -> str:
        # Always write blob first — it is the source of truth for get_task_handoff.
        # Index can be rebuilt from blob if needed, but blob without index is still readable.
        blob_path = self._blob_path("task_handoffs", handoff.id)
        blob_path.write_text(json.dumps(handoff.to_dict(), indent=2, default=str))
        row = {
            "id": handoff.id,
            "project_name": handoff.project_name,
            "task_id": handoff.task_id,
            "summary": handoff.summary,
            "status": handoff.status,
            "last_activity": handoff.last_activity,
            "next_steps": handoff.next_steps,
            "blockers": handoff.blockers,
            "context": handoff.context,
            "created_at": handoff.created_at,
            "updated_at": handoff.updated_at,
        }
        try:
            exists = await asyncio.to_thread(
                self._index.get, "task_handoffs", handoff.id
            )
            if exists:
                await asyncio.to_thread(
                    self._index.update, "task_handoffs", handoff.id, row
                )
            else:
                await asyncio.to_thread(self._index.insert, "task_handoffs", row)
        except Exception:
            # Blob is already persisted; index will be re-synced on next save.
            # Do not delete or modify the blob — it is the ground truth.
            raise
        return handoff.id

    async def get_task_handoff(self, id: str) -> TaskHandoff | None:
        blob_path = self._blob_path("task_handoffs", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return TaskHandoff.from_dict(data)

    async def get_latest_handoffs(
        self,
        project_name: str,
        limit: int = 5,
    ) -> list[TaskHandoff]:
        rows = await asyncio.to_thread(
            self._index.list,
            "task_handoffs",
            "project_name = ?",
            (project_name,),
            order_by="last_activity DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("task_handoffs", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(TaskHandoff.from_dict(data))
        return results

    # ---- RuleCandidate ----
