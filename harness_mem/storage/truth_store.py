"""Canonical truth boundary for structured memory records."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_mem.storage.local_structured_store import LocalStructuredStore


class TruthStore:
    """Small boundary around durable structured truth.

    LocalStructuredStore remains the compatibility facade. This class owns the
    canonical truth collection mapping and multi-record truth updates so callers
    do not need to treat the derived index as durable storage.
    """

    _COLLECTIONS = {
        "memory_entry": "memory_entries",
        "relation_fact": "relation_facts",
        "confirmed_rule": "confirmed_rules",
    }

    def __init__(self, store: LocalStructuredStore):
        self._store = store

    def collection_for_type(self, truth_type: str) -> str:
        try:
            return self._COLLECTIONS[truth_type]
        except KeyError as exc:
            raise ValueError(
                "truth type must be one of: memory_entry, relation_fact, confirmed_rule"
            ) from exc

    def load(
        self,
        truth_type: str,
        truth_id: str,
    ) -> tuple[str, dict[str, Any]] | None:
        collection = self.collection_for_type(truth_type)
        if not self._store.record_payload_exists(collection, truth_id):
            return None
        payload = self._store.read_record_payload(collection, truth_id)
        return collection, payload

    def apply_supersede_updates(
        self,
        data: dict[str, Any],
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> dict[str, Any]:
        updated = dict(data)
        if valid_to is not None:
            updated["valid_to"] = valid_to.isoformat()
        if add_supersedes:
            supersedes = list(updated.get("supersedes") or [])
            if add_supersedes not in supersedes:
                supersedes.append(add_supersedes)
            updated["supersedes"] = supersedes
        if add_superseded_by:
            superseded_by = list(updated.get("superseded_by") or [])
            if add_superseded_by not in superseded_by:
                superseded_by.append(add_superseded_by)
            updated["superseded_by"] = superseded_by
        return updated

    async def persist_snapshot(
        self,
        collection: str,
        truth_id: str,
        data: dict[str, Any],
    ) -> bool:
        if not self._store.record_payload_exists(collection, truth_id):
            return False

        self._store.write_record_payload(collection, truth_id, data)
        updates: dict[str, object] = {}
        for key in ("valid_to", "supersedes", "superseded_by"):
            if key in data:
                updates[key] = data[key]
        if updates:
            updated = await asyncio.to_thread(
                self._store.index.update,
                collection,
                truth_id,
                updates,
            )
            if not updated:
                return False
        return True

    async def update_supersede_fields(
        self,
        truth_type: str,
        truth_id: str,
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> bool:
        loaded = self.load(truth_type, truth_id)
        if loaded is None:
            return False
        collection, data = loaded
        updated = self.apply_supersede_updates(
            data,
            valid_to=valid_to,
            add_supersedes=add_supersedes,
            add_superseded_by=add_superseded_by,
        )
        return await self.persist_snapshot(collection, truth_id, updated)
