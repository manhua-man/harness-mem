"""
AI-led Distillation Bridge — Import memory drafts from AI skills.
==============================================================
This tool bridges the gap between AI-driven distillation skills
(like session-distill / packet-memory-export) and the harness-mem
structured storage candidate layer.

It reads JSON drafts and saves them as 'pending' entries for human review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class ImportBridge:
    def __init__(self, backend: LocalMemoryBackend):
        self.backend = backend

    async def import_file(self, file_path: Path, project_name: str | None = None) -> dict[str, int]:
        """Import entries from a JSON file (draft or sync-list)."""
        if not file_path.exists():
            raise FileNotFoundError(f"Import file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle both single objects and lists
        items = data if isinstance(data, list) else [data]
        
        counts = {"memory_entries": 0, "relation_facts": 0}
        
        for item in items:
            # Determine if it's a relation fact or a regular memory entry
            if self._is_relation_fact(item):
                fact = self._map_to_relation_fact(item, project_name)
                await self.backend.structured_store.save_relation_fact(fact)
                counts["relation_facts"] += 1
            else:
                entry = self._map_to_memory_entry(item, project_name)
                await self.backend.structured_store.save_memory_entry(entry)
                counts["memory_entries"] += 1
                
        return counts

    def _is_relation_fact(self, item: dict[str, Any]) -> bool:
        """Heuristic to detect relation facts."""
        return all(k in item for k in ("source_entity", "target_entity", "relation_type"))

    def _map_to_memory_entry(self, item: dict[str, Any], project_name: str | None) -> MemoryEntry:
        """Map AI draft JSON to MemoryEntry."""
        # Handle 'packet-memory-export' schema or generic AI output
        content = item.get("content") or item.get("conclusion") or item.get("pattern") or str(item)
        category = item.get("category") or "decision"
        source = item.get("source") or item.get("session_id") or "ai-bridge"
        
        # Mapping labels to confidence or tags
        label = item.get("label") or item.get("status") or "new"
        tags = item.get("tags") or []
        if label not in tags:
            tags.append(f"skill-label:{label}")
            
        provenance = item.get("provenance") or {}
        if not provenance and "session_id" in item:
            provenance = {"session_id": item["session_id"], "tool": "import-bridge"}

        return MemoryEntry(
            id=item.get("id") or str(uuid4()),
            project_name=project_name or item.get("project_name") or "unknown",
            category=category,
            content=content,
            source=source,
            status="pending",  # Always pending via bridge
            confidence=float(item.get("confidence", 0.7)),
            tags=tags,
            provenance=provenance
        )

    def _map_to_relation_fact(self, item: dict[str, Any], project_name: str | None) -> RelationFact:
        """Map AI draft JSON to RelationFact."""
        return RelationFact(
            id=item.get("id") or str(uuid4()),
            project_name=project_name or item.get("project_name") or "unknown",
            source_entity=item["source_entity"],
            target_entity=item["target_entity"],
            relation_type=item["relation_type"],
            evidence=item.get("evidence") or item.get("reason") or "Imported via bridge",
            source=item.get("source") or item.get("session_id") or "ai-bridge",
            status="pending",
            confidence=float(item.get("confidence", 0.7)),
            provenance=item.get("provenance") or {"session_id": item.get("session_id")}
        )
