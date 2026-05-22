"""LocalStructuredStore — JSON + SQLite implementation of StructuredStore."""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.core.schemas.procedural_candidate import ProceduralCandidate
from harness_mem.core.schemas.skill import Skill
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
            "supersede_candidates": self.blob_dir / "supersede_candidates",
            "procedural_candidates": self.blob_dir / "procedural_candidates",
            "skills": self.blob_dir / "skills",
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

    def _current_only_clause(self) -> tuple[str, tuple[str]]:
        now = datetime.now(timezone.utc).isoformat()
        return "(valid_to IS NULL OR valid_to = '' OR valid_to > ?)", (now,)

    def _is_current_data(self, data: dict) -> bool:
        valid_to = data.get("valid_to")
        if not valid_to:
            return True
        if isinstance(valid_to, str):
            valid_to = datetime.fromisoformat(valid_to)
        if valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        return valid_to > datetime.now(timezone.utc)

    def _time_window_clause(
        self,
        time_window: tuple[datetime | None, datetime | None] | None,
        *,
        time_columns: tuple[str, ...] = ("recorded_at", "valid_from", "created_at"),
    ) -> tuple[str, tuple[str, ...]]:
        if not time_window:
            return "", ()

        start, end = _normalize_time_window(time_window)
        clauses: list[str] = []
        params: list[str] = []
        coalesced = "COALESCE(" + ", ".join(time_columns) + ")"
        if start is not None:
            clauses.append(f"{coalesced} >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append(f"{coalesced} < ?")
            params.append(end.isoformat())
        return " AND ".join(clauses), tuple(params)

    def _truth_in_time_window(
        self,
        data: dict,
        time_window: tuple[datetime | None, datetime | None] | None,
    ) -> bool:
        if not time_window:
            return True
        truth_time = (
            _normalize_datetime(data.get("recorded_at"))
            or _normalize_datetime(data.get("valid_from"))
            or _normalize_datetime(data.get("created_at"))
        )
        if truth_time is None:
            return False
        start, end = _normalize_time_window(time_window)
        if start is not None and truth_time < start:
            return False
        if end is not None and truth_time >= end:
            return False
        return True

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

    def _truth_collection_for_type(self, truth_type: str) -> str:
        collections = {
            "memory_entry": "memory_entries",
            "relation_fact": "relation_facts",
            "confirmed_rule": "confirmed_rules",
        }
        try:
            return collections[truth_type]
        except KeyError as exc:
            raise ValueError(
                "truth type must be one of: memory_entry, relation_fact, confirmed_rule"
            ) from exc

    def _procedural_search_text(
        self,
        *,
        activation_condition: str,
        steps: list[str],
        termination_condition: str,
        success_examples: list[str],
        name: str = "",
    ) -> str:
        parts = [
            name,
            activation_condition,
            *steps,
            termination_condition,
            *success_examples,
        ]
        return "\n".join(part for part in parts if part)

    def _skill_name_for_candidate(self, candidate: ProceduralCandidate) -> str:
        activation = candidate.activation_condition.strip().rstrip(".")
        if len(activation) <= 80:
            return activation
        return activation[:77].rstrip() + "..."

    def _load_truth_data(self, truth_type: str, truth_id: str) -> tuple[str, Path, dict] | None:
        collection = self._truth_collection_for_type(truth_type)
        blob_path = self._blob_path(collection, truth_id)
        if not blob_path.exists():
            return None
        return collection, blob_path, json.loads(blob_path.read_text())

    def _apply_truth_supersede_updates(
        self,
        data: dict,
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> dict:
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

    async def _persist_truth_snapshot(self, collection: str, truth_id: str, data: dict) -> bool:
        blob_path = self._blob_path(collection, truth_id)
        if not blob_path.exists():
            return False

        blob_path.write_text(json.dumps(data, indent=2, default=str))
        updates: dict[str, object] = {}
        for key in ("valid_to", "supersedes", "superseded_by"):
            if key in data:
                updates[key] = data[key]
        if updates:
            updated = await asyncio.to_thread(self._index.update, collection, truth_id, updates)
            if not updated:
                return False
        return True

    async def _update_truth_supersede_fields(
        self,
        truth_type: str,
        truth_id: str,
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> bool:
        loaded = self._load_truth_data(truth_type, truth_id)
        if loaded is None:
            return False
        collection, blob_path, data = loaded

        updates: dict[str, object] = {}
        if valid_to is not None:
            data["valid_to"] = valid_to.isoformat()
            updates["valid_to"] = valid_to
        if add_supersedes:
            supersedes = list(data.get("supersedes") or [])
            if add_supersedes not in supersedes:
                supersedes.append(add_supersedes)
            data["supersedes"] = supersedes
            updates["supersedes"] = supersedes
        if add_superseded_by:
            superseded_by = list(data.get("superseded_by") or [])
            if add_superseded_by not in superseded_by:
                superseded_by.append(add_superseded_by)
            data["superseded_by"] = superseded_by
            updates["superseded_by"] = superseded_by

        blob_path.write_text(json.dumps(data, indent=2, default=str))
        if updates:
            await asyncio.to_thread(self._index.update, collection, truth_id, updates)
        return True

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
        status: str = "accepted",
        include_history: bool = False,
    ) -> list[MemoryEntry]:
        where_parts = [
            "project_name = ?",
            "COALESCE(compacted, 0) = 0",
            "COALESCE(status, 'accepted') = ?",
        ]
        params = [project_name, status]
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
                # If specifically listing accepted, but blob says otherwise, skip
                if status == "accepted" and data.get("status", "accepted") != "accepted":
                    continue
                if not include_history and not self._is_current_data(data):
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
        include_history: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
    ) -> list[MemoryEntry]:
        extra_where_parts = [
            "COALESCE(compacted, 0) = 0",
            "COALESCE(status, 'accepted') = ?",
        ]
        extra_params: tuple = (status,)
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
                if data.get("status", "accepted") != status:
                    continue
                if memory_type and data.get("memory_type", "semantic") not in memory_type:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._truth_in_time_window(data, time_window):
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

    # ---- SupersedeCandidate ----

    async def save_supersede_candidate(self, candidate: SupersedeCandidate) -> str:
        blob_path = self._blob_path("supersede_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "supersede_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_type": candidate.target_type,
                "target_id": candidate.target_id,
                "replacement_type": candidate.replacement_type,
                "replacement_id": candidate.replacement_id,
                "reason": candidate.reason,
                "evidence": candidate.evidence,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "source": candidate.source,
                "created_at": candidate.created_at,
                "reviewed_at": candidate.reviewed_at,
                "reviewer_id": candidate.reviewer_id,
            },
        )
        return candidate.id

    async def get_supersede_candidate(self, id: str) -> SupersedeCandidate | None:
        blob_path = self._blob_path("supersede_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return SupersedeCandidate.from_dict(data)

    async def list_supersede_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[SupersedeCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "supersede_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("supersede_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(SupersedeCandidate.from_dict(data))
        return results

    async def update_supersede_candidate_status(
        self,
        id: str,
        status: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> bool:
        blob_path = self._blob_path("supersede_candidates", id)
        if not blob_path.exists():
            return False

        reviewed_at = reviewed_at or datetime.now(timezone.utc)
        updates: dict[str, object | None] = {
            "status": status,
            "reviewed_at": reviewed_at,
            "reviewer_id": reviewer_id,
        }
        updated = await asyncio.to_thread(
            self._index.update,
            "supersede_candidates",
            id,
            updates,
        )
        if not updated:
            return False

        data = json.loads(blob_path.read_text())
        data["status"] = status
        data["reviewed_at"] = reviewed_at.isoformat()
        data["reviewer_id"] = reviewer_id
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        return True

    async def confirm_supersede_candidate(
        self,
        id: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> SupersedeCandidate | None:
        candidate = await self.get_supersede_candidate(id)
        if candidate is None or candidate.status != "pending":
            return None
        if candidate.target_type == candidate.replacement_type and candidate.target_id == candidate.replacement_id:
            return None

        reviewed_at = reviewed_at or datetime.now(timezone.utc)
        try:
            target_loaded = self._load_truth_data(candidate.target_type, candidate.target_id)
            replacement_loaded = self._load_truth_data(candidate.replacement_type, candidate.replacement_id)
        except ValueError:
            return None
        if target_loaded is None or replacement_loaded is None:
            return None

        target_collection, _, target_original = target_loaded
        replacement_collection, _, replacement_original = replacement_loaded

        target_updated = self._apply_truth_supersede_updates(
            target_original,
            valid_to=reviewed_at,
            add_superseded_by=candidate.replacement_id,
        )
        replacement_updated = self._apply_truth_supersede_updates(
            replacement_original,
            add_supersedes=candidate.target_id,
        )
        if not await self._persist_truth_snapshot(target_collection, candidate.target_id, target_updated):
            return None
        if not await self._persist_truth_snapshot(replacement_collection, candidate.replacement_id, replacement_updated):
            await self._persist_truth_snapshot(target_collection, candidate.target_id, target_original)
            return None
        if not await self.update_supersede_candidate_status(
            id,
            "accepted",
            reviewed_at=reviewed_at,
            reviewer_id=reviewer_id,
        ):
            await self._persist_truth_snapshot(replacement_collection, candidate.replacement_id, replacement_original)
            await self._persist_truth_snapshot(target_collection, candidate.target_id, target_original)
            return None
        return await self.get_supersede_candidate(id)

    # ---- ProceduralCandidate ----

    async def save_procedural_candidate(self, candidate: ProceduralCandidate) -> str:
        blob_path = self._blob_path("procedural_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "procedural_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "activation_condition": candidate.activation_condition,
                "steps": candidate.steps,
                "termination_condition": candidate.termination_condition,
                "success_examples": candidate.success_examples,
                "source_session_id": candidate.source_session_id,
                "source": candidate.source,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "created_at": candidate.created_at,
                "search_text": self._procedural_search_text(
                    activation_condition=candidate.activation_condition,
                    steps=candidate.steps,
                    termination_condition=candidate.termination_condition,
                    success_examples=candidate.success_examples,
                ),
            },
        )
        return candidate.id

    async def get_procedural_candidate(self, id: str) -> ProceduralCandidate | None:
        blob_path = self._blob_path("procedural_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return ProceduralCandidate.from_dict(data)

    async def list_procedural_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[ProceduralCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "procedural_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("procedural_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(ProceduralCandidate.from_dict(data))
        return results

    async def update_procedural_candidate_status(self, id: str, status: str) -> bool:
        blob_path = self._blob_path("procedural_candidates", id)
        if not blob_path.exists():
            return False

        updated = await asyncio.to_thread(
            self._index.update,
            "procedural_candidates",
            id,
            {"status": status},
        )
        if not updated:
            return False

        data = json.loads(blob_path.read_text())
        data["status"] = status
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        return True

    async def confirm_procedural_candidate(self, id: str) -> Skill | None:
        candidate = await self.get_procedural_candidate(id)
        if candidate is None or candidate.status != "pending":
            return None

        now = datetime.now(timezone.utc)
        skill = Skill(
            project_name=candidate.project_name,
            name=self._skill_name_for_candidate(candidate),
            activation_condition=candidate.activation_condition,
            steps=candidate.steps,
            termination_condition=candidate.termination_condition,
            success_examples=candidate.success_examples,
            source_candidate_id=candidate.id,
            source_session_id=candidate.source_session_id,
            confidence=candidate.confidence,
            created_at=now,
            updated_at=now,
        )
        await self.save_skill(skill)
        updated = await self.update_procedural_candidate_status(candidate.id, "accepted")
        if not updated:
            return None
        return skill

    # ---- Skill ----

    async def save_skill(self, skill: Skill) -> str:
        blob_path = self._blob_path("skills", skill.id)
        blob_path.write_text(json.dumps(skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "skills",
            {
                "id": skill.id,
                "project_name": skill.project_name,
                "name": skill.name,
                "activation_condition": skill.activation_condition,
                "steps": skill.steps,
                "termination_condition": skill.termination_condition,
                "success_examples": skill.success_examples,
                "source_candidate_id": skill.source_candidate_id,
                "source_session_id": skill.source_session_id,
                "confidence": skill.confidence,
                "status": skill.status,
                "usage_count": skill.usage_count,
                "success_count": skill.success_count,
                "failure_count": skill.failure_count,
                "success_rate": skill.success_rate,
                "created_at": skill.created_at,
                "updated_at": skill.updated_at,
                "last_used_at": skill.last_used_at,
                "search_text": self._procedural_search_text(
                    name=skill.name,
                    activation_condition=skill.activation_condition,
                    steps=skill.steps,
                    termination_condition=skill.termination_condition,
                    success_examples=skill.success_examples,
                ),
            },
        )
        return skill.id

    async def get_skill(self, id: str) -> Skill | None:
        blob_path = self._blob_path("skills", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return Skill.from_dict(data)

    async def list_skills(
        self,
        project_name: str,
        status: str = "active",
    ) -> list[Skill]:
        rows = await asyncio.to_thread(
            self._index.list,
            "skills",
            "project_name = ? AND COALESCE(status, 'active') = ?",
            (project_name, status),
            order_by="updated_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("skills", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Skill.from_dict(data))
        return results

    async def search_skills(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 10,
        status: str = "active",
    ) -> list[Skill]:
        extra_where_parts = ["COALESCE(status, 'active') = ?"]
        extra_params: tuple = (status,)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)

        rows = await asyncio.to_thread(
            self._index.search,
            "skills",
            query,
            limit,
            " AND ".join(extra_where_parts),
            extra_params,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("skills", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("status", "active") != status:
                    continue
                if "_fts_score" in row:
                    data["_fts_score"] = row["_fts_score"]
                results.append(Skill.from_dict(data))
        return results

    async def record_skill_result(
        self,
        id: str,
        *,
        success: bool,
        used_at: datetime | None = None,
    ) -> Skill | None:
        skill = await self.get_skill(id)
        if skill is None:
            return None
        updated_skill = skill.record_result(success=success, used_at=used_at)
        blob_path = self._blob_path("skills", updated_skill.id)
        blob_path.write_text(json.dumps(updated_skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "skills",
            updated_skill.id,
            {
                "usage_count": updated_skill.usage_count,
                "success_count": updated_skill.success_count,
                "failure_count": updated_skill.failure_count,
                "success_rate": updated_skill.success_rate,
                "updated_at": updated_skill.updated_at,
                "last_used_at": updated_skill.last_used_at,
            },
        )
        return updated_skill

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
                "usage_count": rule.usage_count,
                "last_surfaced_at": rule.last_surfaced_at,
                "valid_from": rule.valid_from,
                "valid_to": rule.valid_to,
                "recorded_at": rule.recorded_at,
                "supersedes": rule.supersedes,
                "superseded_by": rule.superseded_by,
            },
        )
        return rule.id

    async def get_confirmed_rule(self, id: str) -> ConfirmedRule | None:
        blob_path = self._blob_path("confirmed_rules", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return ConfirmedRule.from_dict(data)

    async def touch_confirmed_rule(
        self, id: str, accessed_at: datetime | None = None
    ) -> bool:
        """Record that a confirmed rule was surfaced (e.g. by wake-up).

        Increments ``usage_count`` and updates ``last_surfaced_at`` on the
        blob and the index. Mirrors :meth:`touch_memory_entry` so wake-up
        and search can use a uniform "I just showed this to a user" signal
        regardless of which structured truth type they touched.
        """
        blob_path = self._blob_path("confirmed_rules", id)
        if not blob_path.exists():
            return False

        touched_at = accessed_at or datetime.now(timezone.utc)
        data = json.loads(blob_path.read_text())
        usage_count = int(data.get("usage_count") or 0) + 1
        data["usage_count"] = usage_count
        data["last_surfaced_at"] = touched_at.isoformat()
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "confirmed_rules",
            id,
            {
                "usage_count": usage_count,
                "last_surfaced_at": touched_at,
            },
        )
        return True

    async def list_confirmed_rules(
        self,
        project_name: str,
        include_history: bool = False,
    ) -> list[ConfirmedRule]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if not include_history:
            clause, clause_params = self._current_only_clause()
            where_parts.append(clause)
            params.extend(clause_params)
        rows = await asyncio.to_thread(
            self._index.list,
            "confirmed_rules",
            " AND ".join(where_parts),
            tuple(params),
            order_by="confirmed_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("confirmed_rules", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if not include_history and not self._is_current_data(data):
                    continue
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
                "valid_from": fact.valid_from,
                "valid_to": fact.valid_to,
                "recorded_at": fact.recorded_at,
                "supersedes": fact.supersedes,
                "superseded_by": fact.superseded_by,
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
        include_history: bool = False,
    ) -> list[RelationFact]:
        where_parts = [
            "project_name = ?",
            "COALESCE(status, 'accepted') = ?",
        ]
        params = [project_name, status]
        if not include_history:
            clause, clause_params = self._current_only_clause()
            where_parts.append(clause)
            params.extend(clause_params)
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
                if not include_history and not self._is_current_data(data):
                    continue
                results.append(RelationFact.from_dict(data))
        return results

    async def search_relation_facts(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        status: str = "accepted",
        include_history: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
    ) -> list[RelationFact]:
        extra_where_parts = ["COALESCE(status, 'accepted') = ?"]
        extra_params: tuple = (status,)
        if not include_history:
            clause, clause_params = self._current_only_clause()
            extra_where_parts.append(clause)
            extra_params = (*extra_params, *clause_params)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)
        window_clause, window_params = self._time_window_clause(time_window)
        if window_clause:
            extra_where_parts.append(window_clause)
            extra_params = (*extra_params, *window_params)

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
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._truth_in_time_window(data, time_window):
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


def _normalize_time_window(
    time_window: tuple[datetime | None, datetime | None],
) -> tuple[datetime | None, datetime | None]:
    start, end = time_window
    return _normalize_datetime(start), _normalize_datetime(end)


def _normalize_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        normalized = value
    elif isinstance(value, str) and value:
        try:
            normalized = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized
