"""Candidate-layer write boundary for structured memory records."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_mem.storage.local_structured_store import LocalStructuredStore


class CandidateStore:
    """Small boundary for candidate status writes.

    Candidate records are review-layer data. This keeps their blob/index status
    updates separate from canonical truth mutation while LocalStructuredStore
    remains the public compatibility facade.
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
        if not self._store.record_payload_exists(collection, entity_id):
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

        data = self._store.read_record_payload(collection, entity_id)
        data["status"] = status
        if payload_updates:
            data.update(payload_updates)
        self._store.write_record_payload(collection, entity_id, data)
        return True
