"""LocalStructuredStore — JSON + SQLite implementation of StructuredStore."""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.sqlite_index import SQLiteIndex


class LocalStructuredStore:
    """Structured store backed by JSON blobs + SQLite FTS index.

    Each entity type stored as:
    - JSON blob: data_dir/structured/{type}/{id}.json
    - SQLite index: data_dir/structured_index.sqlite
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.blob_dir = self.data_dir / "structured"
        self._subdirs = {
            "memory_entries": self.blob_dir / "memory_entries",
            "task_handoffs": self.blob_dir / "task_handoffs",
            "rule_candidates": self.blob_dir / "rule_candidates",
            "confirmed_rules": self.blob_dir / "confirmed_rules",
            "relation_facts": self.blob_dir / "relation_facts",
        }
        for subdir in self._subdirs.values():
            subdir.mkdir(parents=True, exist_ok=True)
        self._index = SQLiteIndex(self.data_dir / "structured_index.sqlite")
        self._index.init_db()
        self._search = HybridSearchLayer(self._index)
        self._backfill_confirmed_rule_source_sessions()

    def _blob_path(self, entity_type: str, id: str) -> Path:
        return self._subdirs[entity_type] / f"{id}.json"

    def _backfill_confirmed_rule_source_sessions(self) -> None:
        """Backfill source_session_id for confirmed rules created before v1.1.1."""
        confirmed_rules_dir = self._subdirs["confirmed_rules"]
        rule_candidates_dir = self._subdirs["rule_candidates"]

        for blob_path in confirmed_rules_dir.glob("*.json"):
            try:
                data = json.loads(blob_path.read_text())
            except json.JSONDecodeError:
                continue

            source_session_id = (data.get("source_session_id") or "").strip()
            if not source_session_id:
                source_candidate_id = data.get("source_candidate_id")
                if not source_candidate_id:
                    continue

                candidate_blob = rule_candidates_dir / f"{source_candidate_id}.json"
                if not candidate_blob.exists():
                    continue

                try:
                    candidate_data = json.loads(candidate_blob.read_text())
                except json.JSONDecodeError:
                    continue

                source_session_id = (candidate_data.get("session_id") or "").strip()
                if not source_session_id:
                    continue

                data["source_session_id"] = source_session_id
                blob_path.write_text(json.dumps(data, indent=2, default=str))

            self._sync_confirmed_rule_source_session(data.get("id", ""), source_session_id)

    def _sync_confirmed_rule_source_session(self, rule_id: str, source_session_id: str) -> None:
        if not rule_id or not source_session_id:
            return
        existing = self._index.get("confirmed_rules", rule_id)
        if existing is None:
            return
        self._index.update(
            "confirmed_rules",
            rule_id,
            {"source_session_id": source_session_id},
        )

    # ---- MemoryEntry ----

    async def save_memory_entry(self, entry: MemoryEntry) -> str:
        blob_path = self._blob_path("memory_entries", entry.id)
        blob_path.write_text(json.dumps(entry.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
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
        status: str = "accepted",
    ) -> list[MemoryEntry]:
        where_parts = [
            "project_name = ?",
            "COALESCE(compacted, 0) = 0",
            "COALESCE(status, 'accepted') = ?",
        ]
        params = [project_name, status]
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
                # If specifically listing accepted, but blob says otherwise, skip
                if status == "accepted" and data.get("status", "accepted") != "accepted":
                    continue
                results.append(MemoryEntry.from_dict(data))
        return results

    async def search_memory_entries(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        mode: str = "auto",
        status: str = "accepted",
        memory_type: list[str] | None = None,
    ) -> list[MemoryEntry]:
        extra_where_parts = [
            "COALESCE(compacted, 0) = 0",
            "COALESCE(status, 'accepted') = ?",
        ]
        extra_params: tuple = (status,)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)
        if memory_type:
            placeholders = ",".join(["?"] * len(memory_type))
            extra_where_parts.append(
                f"COALESCE(memory_type, 'semantic') IN ({placeholders})"
            )
            extra_params = (*extra_params, *memory_type)
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
                if data.get("status", "accepted") != status:
                    continue
                if memory_type and data.get("memory_type", "semantic") not in memory_type:
                    continue
                data.update({
                    "_search_mode": search_result.effective_mode,
                    "_search_requested_mode": search_result.requested_mode,
                    "_search_fallback_reason": search_result.fallback_reason,
                })
                if "_fts_score" in row:
                    data["_fts_score"] = row["_fts_score"]
                if "_hybrid_score" in row:
                    data["_hybrid_score"] = row["_hybrid_score"]
                if "_score" in row:
                    data["_score"] = row["_score"]
                results.append(MemoryEntry.from_dict(data))
        return results

    async def update_memory_entry_status(self, id: str, status: str) -> bool:
        """Update the status of a memory entry (e.g. pending -> accepted)."""
        blob_path = self._blob_path("memory_entries", id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
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

    async def touch_memory_entry(self, id: str, accessed_at: datetime | None = None) -> bool:
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
            exists = await asyncio.to_thread(self._index.get, "task_handoffs", handoff.id)
            if exists:
                await asyncio.to_thread(self._index.update, "task_handoffs", handoff.id, row)
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

    async def save_rule_candidate(self, candidate: RuleCandidate) -> str:
        blob_path = self._blob_path("rule_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "rule_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "session_id": candidate.session_id,
                "pattern": candidate.pattern,
                "trigger": candidate.trigger,
                "examples": candidate.examples,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_rule_candidate(self, id: str) -> RuleCandidate | None:
        blob_path = self._blob_path("rule_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return RuleCandidate.from_dict(data)

    async def list_rule_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[RuleCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        where = " AND ".join(where_parts)
        rows = await asyncio.to_thread(
            self._index.list,
            "rule_candidates",
            where,
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("rule_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(RuleCandidate.from_dict(data))
        return results

    async def update_rule_candidate_status(self, id: str, status: str) -> bool:
        blob_path = self._blob_path("rule_candidates", id)
        if not blob_path.exists():
            return False

        updated = await asyncio.to_thread(
            self._index.update,
            "rule_candidates",
            id,
            {"status": status},
        )
        if not updated:
            return False

        data = json.loads(blob_path.read_text())
        data["status"] = status
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        return True

    # ---- ConfirmedRule ----

    async def save_confirmed_rule(self, rule: ConfirmedRule) -> str:
        blob_path = self._blob_path("confirmed_rules", rule.id)
        blob_path.write_text(json.dumps(rule.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "confirmed_rules",
            {
                "id": rule.id,
                "project_name": rule.project_name,
                "pattern": rule.pattern,
                "trigger": rule.trigger,
                "examples": rule.examples,
                "confirmed_at": rule.confirmed_at,
                "source_candidate_id": rule.source_candidate_id,
                "source_session_id": rule.source_session_id,
                "tags": rule.tags,
            },
        )
        return rule.id

    async def get_confirmed_rule(self, id: str) -> ConfirmedRule | None:
        blob_path = self._blob_path("confirmed_rules", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return ConfirmedRule.from_dict(data)

    async def list_confirmed_rules(self, project_name: str) -> list[ConfirmedRule]:
        rows = await asyncio.to_thread(
            self._index.list,
            "confirmed_rules",
            "project_name = ?",
            (project_name,),
            order_by="confirmed_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("confirmed_rules", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(ConfirmedRule.from_dict(data))
        return results

    # ---- RelationFact ----

    async def save_relation_fact(self, fact: RelationFact) -> str:
        blob_path = self._blob_path("relation_facts", fact.id)
        blob_path.write_text(json.dumps(fact.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "relation_facts",
            {
                "id": fact.id,
                "project_name": fact.project_name,
                "source_entity": fact.source_entity,
                "target_entity": fact.target_entity,
                "relation_type": fact.relation_type,
                "confidence": fact.confidence,
                "status": fact.status,
                "evidence": fact.evidence,
                "source": fact.source,
                "created_at": fact.created_at,
                "updated_at": fact.updated_at,
                "tags": fact.tags,
            },
        )
        return fact.id

    async def get_relation_fact(self, id: str) -> RelationFact | None:
        blob_path = self._blob_path("relation_facts", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return RelationFact.from_dict(data)

    async def list_relation_facts(
        self,
        project_name: str,
        source_entity: str | None = None,
        target_entity: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
        status: str = "accepted",
    ) -> list[RelationFact]:
        where_parts = [
            "project_name = ?",
            "COALESCE(status, 'accepted') = ?",
        ]
        params = [project_name, status]
        if source_entity:
            where_parts.append("source_entity = ?")
            params.append(source_entity)
        if target_entity:
            where_parts.append("target_entity = ?")
            params.append(target_entity)
        if relation_type:
            where_parts.append("relation_type = ?")
            params.append(relation_type)

        rows = await asyncio.to_thread(
            self._index.list,
            "relation_facts",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("relation_facts", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("status", "accepted") != status:
                    continue
                results.append(RelationFact.from_dict(data))
        return results

    async def search_relation_facts(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        status: str = "accepted",
    ) -> list[RelationFact]:
        extra_where_parts = ["COALESCE(status, 'accepted') = ?"]
        extra_params: tuple = (status,)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)

        rows = await asyncio.to_thread(
            self._index.search,
            "relation_facts",
            query,
            limit,
            " AND ".join(extra_where_parts) if extra_where_parts else None,
            extra_params,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("relation_facts", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("status", "accepted") != status:
                    continue
                if "_fts_score" in row:
                    data["_fts_score"] = row["_fts_score"]
                results.append(RelationFact.from_dict(data))
        return results

    async def update_relation_fact_status(self, id: str, status: str) -> bool:
        """Update the status of a relation fact."""
        blob_path = self._blob_path("relation_facts", id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
        data["status"] = status
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "relation_facts",
            id,
            {"status": status},
        )
        return True

    def close(self) -> None:
        self._index.close()
