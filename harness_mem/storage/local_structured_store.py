"""LocalStructuredStore — JSON + SQLite implementation of StructuredStore."""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.procedural_candidate import ProceduralCandidate
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.metabolism_run import MetabolismRun
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.candidate_store import CandidateStore
from harness_mem.storage.canonical_store import CanonicalStoreRuntime
from harness_mem.storage.derived_index import DerivedIndex
from harness_mem.storage.sqlite_index import SQLiteIndex
from harness_mem.storage.truth_store import TruthStore
from harness_mem.governance_status import (
    GOVERNANCE_STATUSES,
    READABLE_TRUTH_FILTER,
    statuses_for_list_filter,
    user_confirm_status,
    validate_status_transition,
)


_SEARCH_SCORE_FIELDS = (
    "_fts_score",
    "_fts_score_total",
    "_fts_match_count",
    "_fts_rank",
    "_vec_rank",
    "_vec_sim",
    "_fts_factor",
    "_vec_factor",
    "_rrf_score",
    "_hybrid_score",
    "_score",
)


def _copy_search_score_fields(data: dict[str, Any], row: dict[str, Any]) -> None:
    for field in _SEARCH_SCORE_FIELDS:
        if field in row:
            data[field] = row[field]


class _CanonicalStructuredBlobPath:
    """Path-like shim that stores payload JSON in canonical SQLite truth."""

    def __init__(self, store: "LocalStructuredStore", collection: str, entity_id: str):
        self._store = store
        self._collection = collection
        self._entity_id = entity_id

    def exists(self) -> bool:
        canonical = self._store._canonical
        return bool(canonical and canonical.payload_exists(self._collection, self._entity_id))

    def read_text(self, *_args, **_kwargs) -> str:
        canonical = self._store._canonical
        if canonical is None:
            raise FileNotFoundError(self._entity_id)
        payload_json = canonical.get_payload_json(self._collection, self._entity_id)
        if payload_json is None:
            raise FileNotFoundError(self._entity_id)
        return payload_json

    def write_text(self, data: str, *_args, **_kwargs) -> int:
        canonical = self._store._canonical
        if canonical is None:
            raise RuntimeError("canonical runtime is not enabled")
        payload = json.loads(data)
        canonical.upsert_payload(
            self._collection,
            self._entity_id,
            payload,
            source_relpath=self._store._canonical_source_relpath(self._collection, self._entity_id),
        )
        return len(data)

    def unlink(self) -> None:
        canonical = self._store._canonical
        if canonical is None:
            raise FileNotFoundError(self._entity_id)
        if not canonical.delete_payload(self._collection, self._entity_id):
            raise FileNotFoundError(self._entity_id)


class LocalStructuredStore:
    """Structured store backed by JSON blobs + SQLite FTS index.

    Each entity type stored as:
    - JSON blob: data_dir/structured/{type}/{id}.json
    - SQLite index: data_dir/structured_index.sqlite
    """

    def __init__(self, data_dir: Path, *, canonical_mode: bool = True):
        self.data_dir = Path(data_dir)
        self.blob_dir = self.data_dir / "structured"
        self.canonical_mode = canonical_mode
        self._canonical = CanonicalStoreRuntime(self.data_dir) if canonical_mode else None
        self._subdirs = {
            "memory_entries": self.blob_dir / "memory_entries",
            "task_handoffs": self.blob_dir / "task_handoffs",
            "rule_candidates": self.blob_dir / "rule_candidates",
            "supersede_candidates": self.blob_dir / "supersede_candidates",
            "procedural_candidates": self.blob_dir / "procedural_candidates",
            "skills": self.blob_dir / "skills",
            "confirmed_rules": self.blob_dir / "confirmed_rules",
            "relation_facts": self.blob_dir / "relation_facts",
            "metabolism_runs": self.blob_dir / "metabolism_runs",
            "dream_runs": self.blob_dir / "dream_runs",
            "retrieval_signals": self.blob_dir / "retrieval_signals",
            "merge_suggestion_candidates": self.blob_dir / "merge_suggestion_candidates",
            "stale_truth_suggestion_candidates": (
                self.blob_dir / "stale_truth_suggestion_candidates"
            ),
        }
        for subdir in self._subdirs.values():
            subdir.mkdir(parents=True, exist_ok=True)
        self._index = SQLiteIndex(self.data_dir / "structured_index.sqlite")
        self._index.init_db()
        self._search = HybridSearchLayer(self._index)
        self.truth_store = TruthStore(self)
        self.candidate_store = CandidateStore(self)
        if not self.canonical_mode:
            self._backfill_confirmed_rule_source_sessions()

    async def init_runtime(self) -> None:
        if self.canonical_mode:
            await self._sync_missing_index_rows_from_canonical()
        self._backfill_confirmed_rule_source_sessions()

    def _blob_path(self, entity_type: str, id: str) -> Path | _CanonicalStructuredBlobPath:
        if self.canonical_mode:
            return _CanonicalStructuredBlobPath(self, entity_type, id)
        return self._subdirs[entity_type] / f"{id}.json"

    def record_payload_exists(self, collection: str, entity_id: str) -> bool:
        """Return whether a structured record payload exists.

        This is the explicit blob/canonical boundary used by smaller stores so
        they do not need to depend on the private path implementation.
        """
        return self._blob_path(collection, entity_id).exists()

    def read_record_payload(self, collection: str, entity_id: str) -> dict[str, Any]:
        """Read one structured record payload by collection/id."""
        return json.loads(self._blob_path(collection, entity_id).read_text())

    def write_record_payload(
        self,
        collection: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist one structured record payload by collection/id."""
        self._blob_path(collection, entity_id).write_text(
            json.dumps(payload, indent=2, default=str)
        )

    @property
    def index(self) -> DerivedIndex:
        """Shared derived index owned by this store's lifecycle.

        Exposed for stores that intentionally share the structured SQLite
        read model without reaching into private attributes.
        """

        return self._index

    @staticmethod
    def _canonical_source_relpath(entity_type: str, id: str) -> str:
        return f"structured/{entity_type}/{id}.json"

    def _current_only_clause(self) -> tuple[str, tuple[str]]:
        now = datetime.now(timezone.utc).isoformat()
        return (
            "(valid_to IS NULL OR valid_to = '' OR valid_to > ?) "
            "AND (superseded_by IS NULL OR superseded_by = '' OR superseded_by = '[]')",
            (now,),
        )

    def _is_current_data(self, data: dict) -> bool:
        if _has_superseded_by(data):
            return False
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

    def _tier_visible(self, data: dict, *, deep_recall: bool) -> bool:
        if deep_recall:
            return True
        tier = str(data.get("tier") or "hot")
        return tier in {"hot", "warm"}

    def _backfill_confirmed_rule_source_sessions(self) -> None:
        """Backfill source_session_id for confirmed rules created before v1.1.1."""
        if self.canonical_mode:
            canonical = self._canonical
            if canonical is None:
                return
            for data in canonical.list_payloads("confirmed_rules"):
                rule_id = str(data.get("id") or "").strip()
                source_session_id = str(data.get("source_session_id") or "").strip()
                if source_session_id:
                    self._sync_confirmed_rule_source_session(rule_id, source_session_id)
                    continue
                source_candidate_id = str(data.get("source_candidate_id") or "").strip()
                if not source_candidate_id:
                    continue
                candidate_data = canonical.get_payload("rule_candidates", source_candidate_id)
                if not isinstance(candidate_data, dict):
                    continue
                source_session_id = str(candidate_data.get("session_id") or "").strip()
                if not source_session_id:
                    continue
                data["source_session_id"] = source_session_id
                canonical.upsert_payload(
                    "confirmed_rules",
                    rule_id,
                    data,
                    source_relpath=self._canonical_source_relpath("confirmed_rules", rule_id),
                )
                self._sync_confirmed_rule_source_session(rule_id, source_session_id)
            return

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
        return self.truth_store.collection_for_type(truth_type)

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

    async def _find_existing_shared_skill(
        self,
        *,
        source_skill_id: str,
        requested_scope: str,
    ) -> Skill | None:
        rows = await asyncio.to_thread(
            self._index.list,
            "skills",
            "COALESCE(scope, 'project') = ?",
            (requested_scope,),
            order_by="updated_at DESC",
        )
        for row in rows:
            blob_path = self._blob_path("skills", row["id"])
            if not blob_path.exists():
                continue
            data = json.loads(blob_path.read_text())
            if source_skill_id in list(data.get("source_ids") or []):
                return Skill.from_dict(data)
        return None

    def _load_truth_data(
        self,
        truth_type: str,
        truth_id: str,
    ) -> tuple[str, Path | _CanonicalStructuredBlobPath, dict[str, Any]] | None:
        loaded = self.truth_store.load(truth_type, truth_id)
        if loaded is None:
            return None
        collection, payload = loaded
        blob_path = self._blob_path(collection, truth_id)
        return collection, cast(Path | _CanonicalStructuredBlobPath, blob_path), payload

    def _apply_truth_supersede_updates(
        self,
        data: dict,
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> dict:
        return self.truth_store.apply_supersede_updates(
            data,
            valid_to=valid_to,
            add_supersedes=add_supersedes,
            add_superseded_by=add_superseded_by,
        )

    async def _persist_truth_snapshot(self, collection: str, truth_id: str, data: dict) -> bool:
        return await self.truth_store.persist_snapshot(collection, truth_id, data)

    async def _update_truth_supersede_fields(
        self,
        truth_type: str,
        truth_id: str,
        *,
        valid_to: datetime | None = None,
        add_supersedes: str | None = None,
        add_superseded_by: str | None = None,
    ) -> bool:
        return await self.truth_store.update_supersede_fields(
            truth_type,
            truth_id,
            valid_to=valid_to,
            add_supersedes=add_supersedes,
            add_superseded_by=add_superseded_by,
        )

    async def _sync_missing_index_rows_from_canonical(self) -> None:
        canonical = self._canonical
        if canonical is None:
            return

        collections = (
            "memory_entries",
            "task_handoffs",
            "rule_candidates",
            "supersede_candidates",
            "merge_suggestion_candidates",
            "stale_truth_suggestion_candidates",
            "procedural_candidates",
            "skills",
            "confirmed_rules",
            "relation_facts",
            "metabolism_runs",
            "dream_runs",
            "retrieval_signals",
        )
        for collection in collections:
            canonical_count = canonical.count(collection)
            if canonical_count <= 0:
                continue
            indexed_count = await asyncio.to_thread(self._index.count, collection)
            if indexed_count >= canonical_count:
                continue
            for payload in canonical.list_payloads(collection):
                entity_id = str(payload.get("id") or "")
                if not entity_id:
                    continue
                if await asyncio.to_thread(self._index.get, collection, entity_id) is not None:
                    continue
                try:
                    await self._replay_canonical_payload(collection, payload)
                except Exception:
                    # Canonical truth remains authoritative; malformed legacy-era
                    # compatibility payloads should not prevent runtime bootstrap.
                    continue

    async def _replay_canonical_payload(
        self,
        collection: str,
        payload: dict,
    ) -> None:
        if collection == "memory_entries":
            await self.save_memory_entry(MemoryEntry.from_dict(payload))
            return
        if collection == "task_handoffs":
            await self.save_task_handoff(TaskHandoff.from_dict(payload))
            return
        if collection == "rule_candidates":
            await self.save_rule_candidate(RuleCandidate.from_dict(payload))
            return
        if collection == "supersede_candidates":
            await self.save_supersede_candidate(SupersedeCandidate.from_dict(payload))
            return
        if collection == "merge_suggestion_candidates":
            await self.save_merge_suggestion_candidate(
                MergeSuggestionCandidate.from_dict(payload)
            )
            return
        if collection == "stale_truth_suggestion_candidates":
            await self.save_stale_truth_suggestion_candidate(
                StaleTruthSuggestionCandidate.from_dict(payload)
            )
            return
        if collection == "procedural_candidates":
            await self.save_procedural_candidate(ProceduralCandidate.from_dict(payload))
            return
        if collection == "skills":
            await self.save_skill(Skill.from_dict(payload))
            return
        if collection == "confirmed_rules":
            await self.save_confirmed_rule(ConfirmedRule.from_dict(payload))
            return
        if collection == "relation_facts":
            await self.save_relation_fact(RelationFact.from_dict(payload))
            return
        if collection == "metabolism_runs":
            await self.save_metabolism_run(MetabolismRun.from_dict(payload))
            return
        if collection == "dream_runs":
            await self.save_dream_run(DreamRun.from_dict(payload))
            return
        if collection == "retrieval_signals":
            await self.save_retrieval_signal(RetrievalSignal.from_dict(payload))

    # ---- MemoryEntry ----

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
                if memory_type and data.get("memory_type", "semantic") not in memory_type:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._tier_visible(data, deep_recall=deep_recall):
                    continue
                if not self._truth_in_time_window(data, time_window):
                    continue
                data.update({
                    "_search_mode": search_result.effective_mode,
                    "_search_requested_mode": search_result.requested_mode,
                    "_search_fallback_reason": search_result.fallback_reason,
                })
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
            self._index.upsert,
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
        return await self.candidate_store.update_status("rule_candidates", id, status)

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
        reviewed_at = reviewed_at or datetime.now(timezone.utc)
        return await self.candidate_store.update_status(
            "supersede_candidates",
            id,
            status,
            index_updates={
                "reviewed_at": reviewed_at,
                "reviewer_id": reviewer_id,
            },
            payload_updates={
                "reviewed_at": reviewed_at.isoformat(),
                "reviewer_id": reviewer_id,
            },
        )

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
            user_confirm_status(),
            reviewed_at=reviewed_at,
            reviewer_id=reviewer_id,
        ):
            await self._persist_truth_snapshot(replacement_collection, candidate.replacement_id, replacement_original)
            await self._persist_truth_snapshot(target_collection, candidate.target_id, target_original)
            return None
        return await self.get_supersede_candidate(id)

    # ---- MergeSuggestionCandidate ----

    async def save_merge_suggestion_candidate(
        self, candidate: MergeSuggestionCandidate
    ) -> str:
        blob_path = self._blob_path("merge_suggestion_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "merge_suggestion_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_a_id": candidate.target_a_id,
                "target_a_kind": candidate.target_a_kind,
                "target_b_id": candidate.target_b_id,
                "target_b_kind": candidate.target_b_kind,
                "similarity_score": candidate.similarity_score,
                "status": candidate.status,
                "metabolism_run_id": candidate.metabolism_run_id,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_merge_suggestion_candidate(
        self, id: str
    ) -> MergeSuggestionCandidate | None:
        blob_path = self._blob_path("merge_suggestion_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return MergeSuggestionCandidate.from_dict(data)

    async def list_merge_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[MergeSuggestionCandidate]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "merge_suggestion_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results: list[MergeSuggestionCandidate] = []
        for row in rows:
            blob_path = self._blob_path("merge_suggestion_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(MergeSuggestionCandidate.from_dict(data))
        return results

    async def update_merge_suggestion_candidate_status(
        self, id: str, status: str
    ) -> bool:
        return await self.candidate_store.update_status(
            "merge_suggestion_candidates",
            id,
            status,
        )

    # ---- StaleTruthSuggestionCandidate ----

    async def save_stale_truth_suggestion_candidate(
        self, candidate: StaleTruthSuggestionCandidate
    ) -> str:
        blob_path = self._blob_path("stale_truth_suggestion_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "stale_truth_suggestion_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_id": candidate.target_id,
                "target_kind": candidate.target_kind,
                "last_surfaced_at": candidate.last_surfaced_at,
                "days_since_last_surface": candidate.days_since_last_surface,
                "status": candidate.status,
                "metabolism_run_id": candidate.metabolism_run_id,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_stale_truth_suggestion_candidate(
        self, id: str
    ) -> StaleTruthSuggestionCandidate | None:
        blob_path = self._blob_path("stale_truth_suggestion_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return StaleTruthSuggestionCandidate.from_dict(data)

    async def list_stale_truth_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[StaleTruthSuggestionCandidate]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "stale_truth_suggestion_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results: list[StaleTruthSuggestionCandidate] = []
        for row in rows:
            blob_path = self._blob_path("stale_truth_suggestion_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(StaleTruthSuggestionCandidate.from_dict(data))
        return results

    async def update_stale_truth_suggestion_candidate_status(
        self, id: str, status: str
    ) -> bool:
        return await self.candidate_store.update_status(
            "stale_truth_suggestion_candidates",
            id,
            status,
        )

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
        return await self.candidate_store.update_status("procedural_candidates", id, status)

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
            scope="project",
            origin_project=candidate.project_name,
            source_ids=[
                source_id
                for source_id in (candidate.id, candidate.source_session_id, candidate.source)
                if source_id
            ],
            confidence=candidate.confidence,
            created_at=now,
            updated_at=now,
        )
        await self.save_skill(skill)
        updated = await self.update_procedural_candidate_status(
            candidate.id, user_confirm_status()
        )
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
                "scope": skill.scope,
                "origin_project": skill.origin_project,
                "source_ids": skill.source_ids,
                "portability_notes": skill.portability_notes,
                "disabled_assumptions": skill.disabled_assumptions,
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
            "project_name = ? AND COALESCE(status, 'active') = ? AND COALESCE(scope, 'project') = 'project'",
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

    async def list_skills_any_scope(
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
        shared_scope: str = "exclude",
    ) -> list[Skill]:
        if shared_scope not in {"exclude", "include", "only"}:
            raise ValueError("shared_scope must be one of: exclude, include, only")

        def load_rows(rows: list[dict]) -> list[Skill]:
            results: list[Skill] = []
            for row in rows:
                blob_path = self._blob_path("skills", row["id"])
                if not blob_path.exists():
                    continue
                data = json.loads(blob_path.read_text())
                if data.get("status", "active") != status:
                    continue
                _copy_search_score_fields(data, row)
                results.append(Skill.from_dict(data))
            return results

        async def run_search(where_parts: list[str], params: tuple[object, ...]) -> list[Skill]:
            rows = await asyncio.to_thread(
                self._index.search,
                "skills",
                query,
                limit,
                " AND ".join(where_parts),
                params,
            )
            return load_rows(rows)

        if not project_name:
            where_parts = ["COALESCE(status, 'active') = ?"]
            params: tuple[object, ...] = (status,)
            if shared_scope == "only":
                where_parts.append("COALESCE(scope, 'project') IN ('workspace', 'global')")
            return await run_search(where_parts, params)

        project_where_parts = [
            "COALESCE(status, 'active') = ?",
            "project_name = ?",
            "COALESCE(scope, 'project') = 'project'",
        ]
        project_params: tuple[object, ...] = (status, project_name)
        if shared_scope == "exclude":
            return await run_search(project_where_parts, project_params)

        shared_where_parts = [
            "COALESCE(status, 'active') = ?",
            "COALESCE(scope, 'project') IN ('workspace', 'global')",
        ]
        shared_params: tuple[object, ...] = (status,)

        shared_matches = await run_search(shared_where_parts, shared_params)
        if shared_scope == "only":
            return shared_matches[:limit]

        project_matches = await run_search(project_where_parts, project_params)
        ordered_matches: list[Skill] = []
        seen_ids: set[str] = set()
        for skill in [*project_matches, *shared_matches]:
            if skill.id in seen_ids:
                continue
            seen_ids.add(skill.id)
            ordered_matches.append(skill)
            if len(ordered_matches) >= limit:
                break
        return ordered_matches

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

    async def update_skill_status(self, id: str, status: str) -> Skill | None:
        skill = await self.get_skill(id)
        if skill is None:
            return None
        updated_skill = skill.model_copy(
            update={
                "status": status,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        blob_path = self._blob_path("skills", updated_skill.id)
        blob_path.write_text(json.dumps(updated_skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "skills",
            updated_skill.id,
            {
                "status": updated_skill.status,
                "updated_at": updated_skill.updated_at,
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
            self._index.upsert,
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
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        include_provisional: bool = False,
    ) -> list[RelationFact]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        where_parts = [
            "project_name = ?",
            f"COALESCE(status, 'pending') IN ({placeholders})",
        ]
        params: list[Any] = [project_name, *status_filter]
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
                if data.get("status", "pending") not in status_filter:
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
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
        include_provisional: bool = False,
    ) -> list[RelationFact]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        extra_where_parts = [f"COALESCE(status, 'pending') IN ({placeholders})"]
        extra_params: tuple = tuple(status_filter)
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
                if data.get("status", "pending") not in status_filter:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._truth_in_time_window(data, time_window):
                    continue
                _copy_search_score_fields(data, row)
                results.append(RelationFact.from_dict(data))
        return results

    async def update_relation_fact_status(self, id: str, status: str) -> bool:
        """Update the governance status of a relation fact."""
        if status not in GOVERNANCE_STATUSES:
            return False
        blob_path = self._blob_path("relation_facts", id)
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
            "relation_facts",
            id,
            {"status": status},
        )
        return True

    # ---- MetabolismRun ----

    async def save_metabolism_run(self, run: MetabolismRun) -> str:
        """Persist a metabolism run record. Returns run id."""
        blob_path = self._blob_path("metabolism_runs", run.id)
        blob_path.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "metabolism_runs",
            {
                "id": run.id,
                "project_name": run.project_name,
                "kind": run.kind,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "status": run.status,
                "duration_ms": run.duration_ms,
            },
        )
        return run.id

    async def list_metabolism_runs(
        self,
        project_name: str,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MetabolismRun]:
        """List metabolism runs for project, newest first.

        ``kind`` filters to ``"preview"`` or ``"metabolism"`` when set.
        """
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if kind is not None:
            where_parts.append("kind = ?")
            params.append(kind)
        rows = await asyncio.to_thread(
            self._index.list,
            "metabolism_runs",
            " AND ".join(where_parts),
            tuple(params),
            order_by="started_at DESC",
            limit=limit,
        )
        results: list[MetabolismRun] = []
        for row in rows:
            blob_path = self._blob_path("metabolism_runs", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(MetabolismRun.from_dict(data))
        return results

    # ---- DreamRun ----

    async def save_dream_run(self, run: DreamRun) -> str:
        """Persist a dream run ledger record. Returns run id."""
        blob_path = self._blob_path("dream_runs", run.id)
        blob_path.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        row = {
            "id": run.id,
            "project_name": run.project_name,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "status": run.status,
            "trigger_source": run.trigger_source,
            "reflection_job_id": run.reflection_job_id,
            "policy_version": run.policy_version,
            "duration_ms": run.duration_ms,
        }
        if self._index.get("dream_runs", run.id) is None:
            await asyncio.to_thread(self._index.insert, "dream_runs", row)
        else:
            await asyncio.to_thread(self._index.update, "dream_runs", run.id, row)
        return run.id

    async def get_dream_run(self, id: str) -> DreamRun | None:
        blob_path = self._blob_path("dream_runs", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return DreamRun.from_dict(data)

    async def list_dream_runs(
        self,
        project_name: str,
        *,
        limit: int = 20,
    ) -> list[DreamRun]:
        rows = await asyncio.to_thread(
            self._index.list,
            "dream_runs",
            "project_name = ?",
            (project_name,),
            order_by="started_at DESC",
            limit=limit,
        )
        results: list[DreamRun] = []
        for row in rows:
            blob_path = self._blob_path("dream_runs", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(DreamRun.from_dict(data))
        return results

    # ---- RetrievalSignal ----

    async def save_retrieval_signal(self, signal: RetrievalSignal) -> str:
        """Persist a retrieval signal record. Returns signal id."""
        blob_path = self._blob_path("retrieval_signals", signal.id)
        blob_path.write_text(json.dumps(signal.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "retrieval_signals",
            {
                "id": signal.id,
                "project_name": signal.project_name,
                "signal_type": signal.signal_type,
                "target_kind": signal.target_kind,
                "target_id": signal.target_id,
                "recorded_at": signal.recorded_at,
                "value": signal.value,
            },
        )
        return signal.id

    async def query_retrieval_signals(
        self,
        project_name: str,
        *,
        signal_type: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[RetrievalSignal]:
        """Query retrieval signals by filters; newest first.

        Used by the replay-window selector — ``target_id`` filter exists so
        selectors can ask "how many search_hits for this entry id in the
        last week?".
        """
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if signal_type is not None:
            where_parts.append("signal_type = ?")
            params.append(signal_type)
        if target_kind is not None:
            where_parts.append("target_kind = ?")
            params.append(target_kind)
        if target_id is not None:
            where_parts.append("target_id = ?")
            params.append(target_id)
        if since is not None:
            where_parts.append("recorded_at >= ?")
            params.append(since.isoformat())
        rows = await asyncio.to_thread(
            self._index.list,
            "retrieval_signals",
            " AND ".join(where_parts),
            tuple(params),
            order_by="recorded_at DESC",
            limit=limit,
        )
        results: list[RetrievalSignal] = []
        for row in rows:
            blob_path = self._blob_path("retrieval_signals", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(RetrievalSignal.from_dict(data))
        return results

    def close(self) -> None:
        if self._canonical is not None:
            self._canonical.close()
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


def _has_superseded_by(data: dict[str, Any]) -> bool:
    superseded_by = data.get("superseded_by")
    if superseded_by is None:
        return False
    if isinstance(superseded_by, str):
        stripped = superseded_by.strip()
        return stripped not in {"", "[]"}
    if isinstance(superseded_by, list):
        return bool(superseded_by)
    return bool(superseded_by)
