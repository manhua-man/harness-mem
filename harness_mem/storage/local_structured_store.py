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
from harness_mem.storage.structured_store_support import (
    _has_superseded_by,
    _normalize_datetime,
    _normalize_time_window,
)
from harness_mem.storage.structured_store_memory import StructuredMemoryMixin
from harness_mem.storage.structured_store_candidates import StructuredCandidateMixin
from harness_mem.storage.structured_store_truth import StructuredTruthMixin
from harness_mem.storage.structured_store_ledgers import StructuredLedgerMixin


class _CanonicalStructuredBlobPath:
    """Path-like shim that stores payload JSON in canonical SQLite truth."""

    def __init__(self, store: "LocalStructuredStore", collection: str, entity_id: str):
        self._store = store
        self._collection = collection
        self._entity_id = entity_id

    def exists(self) -> bool:
        canonical = self._store._canonical
        return bool(
            canonical and canonical.payload_exists(self._collection, self._entity_id)
        )

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
            source_relpath=self._store._canonical_source_relpath(
                self._collection, self._entity_id
            ),
        )
        return len(data)

    def unlink(self) -> None:
        canonical = self._store._canonical
        if canonical is None:
            raise FileNotFoundError(self._entity_id)
        if not canonical.delete_payload(self._collection, self._entity_id):
            raise FileNotFoundError(self._entity_id)


class LocalStructuredStore(
    StructuredMemoryMixin,
    StructuredCandidateMixin,
    StructuredTruthMixin,
    StructuredLedgerMixin,
):
    def __init__(self, data_dir: Path, *, canonical_mode: bool = True):
        self.data_dir = Path(data_dir)
        self.blob_dir = self.data_dir / "structured"
        self.canonical_mode = canonical_mode
        self._canonical = (
            CanonicalStoreRuntime(self.data_dir) if canonical_mode else None
        )
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
            "merge_suggestion_candidates": self.blob_dir
            / "merge_suggestion_candidates",
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

    def _blob_path(
        self, entity_type: str, id: str
    ) -> Path | _CanonicalStructuredBlobPath:
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

    def list_record_payloads(
        self,
        collection: str,
        *,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """List raw payloads for lifecycle planning without search filtering."""

        if collection not in self._subdirs:
            raise KeyError(collection)
        if self.canonical_mode:
            canonical = self._canonical
            return [] if canonical is None else canonical.list_payloads(collection)
        payloads: list[dict[str, Any]] = []
        for path in self._subdirs[collection].glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                if strict:
                    raise
                continue
            if not isinstance(payload, dict):
                if strict:
                    raise ValueError(f"invalid structured payload: {path.name}")
                continue
            payloads.append(payload)
        return payloads

    def hard_delete_record(self, collection: str, entity_id: str) -> bool:
        """Erase canonical/blob truth and all derived index rows for one record."""

        if collection not in self._subdirs:
            raise KeyError(collection)
        existed = self.record_payload_exists(collection, entity_id)
        self._index.delete(collection, entity_id)
        if existed:
            self._blob_path(collection, entity_id).unlink()
        return existed

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
                candidate_data = canonical.get_payload(
                    "rule_candidates", source_candidate_id
                )
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
                    source_relpath=self._canonical_source_relpath(
                        "confirmed_rules", rule_id
                    ),
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

            self._sync_confirmed_rule_source_session(
                data.get("id", ""), source_session_id
            )

    def _sync_confirmed_rule_source_session(
        self, rule_id: str, source_session_id: str
    ) -> None:
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

    async def _persist_truth_snapshot(
        self, collection: str, truth_id: str, data: dict
    ) -> bool:
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
                if (
                    await asyncio.to_thread(self._index.get, collection, entity_id)
                    is not None
                ):
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

    def flush_sensitive_deletes(self) -> None:
        """Flush canonical and derived-index delete pages from their WALs."""

        if self._canonical is not None:
            self._canonical.flush_sensitive_deletes()
        self._index.flush_sensitive_deletes()

    def close(self) -> None:
        if self._canonical is not None:
            self._canonical.close()
        self._index.close()
