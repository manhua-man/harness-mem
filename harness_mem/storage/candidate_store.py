"""Candidate-layer write boundary for structured memory records."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from harness_mem.governance_status import (
    GOVERNANCE_STATUSES,
    MAINTENANCE_REVIEW_COLLECTIONS,
    is_valid_maintenance_review_status,
    validate_maintenance_review_transition,
    validate_status_transition,
)

if TYPE_CHECKING:
    from harness_mem.storage.local_structured_store import LocalStructuredStore


class CandidateStore:
    """Small boundary for candidate status writes.

    Memory/rule candidates use the seven-state governance table. Dream
    maintenance collections (supersede/merge/stale) use a separate
    pending -> user_confirmed | rejected review table.
    """

    def __init__(self, store: LocalStructuredStore):
        self._store = store

    async def update_status(
        self,
        collection: str,
        entity_id: str,
        status: str,
        *,
        index_updates: dict[str, object | None] | None = None,
        payload_updates: dict[str, Any] | None = None,
    ) -> bool:
        if collection in MAINTENANCE_REVIEW_COLLECTIONS:
            if not is_valid_maintenance_review_status(status):
                return False
        elif status not in GOVERNANCE_STATUSES:
            return False

        if not self._store.record_payload_exists(collection, entity_id):
            return False

        data = self._store.read_record_payload(collection, entity_id)
        current = data.get("status", "pending")
        if collection in MAINTENANCE_REVIEW_COLLECTIONS:
            if not validate_maintenance_review_transition(current, status):
                return False
        elif not validate_status_transition(current, status):
            return False

        index_patch: dict[str, object | None] = {"status": status}
        if index_updates:
            index_patch.update(index_updates)
        updated = await asyncio.to_thread(
            self._store.index.update,
            collection,
            entity_id,
            index_patch,
        )
        if not updated:
            return False

        data["status"] = status
        if payload_updates:
            data.update(payload_updates)
        self._store.write_record_payload(collection, entity_id, data)
        return True