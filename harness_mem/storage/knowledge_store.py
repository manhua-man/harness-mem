"""SQLite-authoritative current knowledge and finite job processing state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    KnowledgeSource,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.knowledge_renderer import render_knowledge_markdown
from harness_mem.storage.knowledge_job_workspace import KnowledgeJobWorkspace

if TYPE_CHECKING:
    from harness_mem.storage.local_structured_store import LocalStructuredStore


_WRITING_DISPOSITIONS = {"add", "refine", "replace"}
_UNRESOLVED_DISPOSITIONS = {"defer", "conflict"}
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeStore:
    """Own clean current knowledge in canonical SQLite.

    Candidate/evidence/proposed-decision records live in a retry-safe job
    workspace and are removed only after the caller has persisted the terminal
    Note/Packet/receipt.  Markdown is a projection returned by ``render_markdown``;
    it is never read or written here.
    """

    def __init__(self, store: LocalStructuredStore):
        self._store = store
        self._workspace = KnowledgeJobWorkspace(store.data_dir)

    @property
    def workspace_root(self):
        return self._workspace.root

    async def save_entry(self, entry: KnowledgeEntry) -> str:
        raise RuntimeError(
            "current knowledge writes require verified assimilation transaction"
        )

    async def get_entry(
        self,
        entry_id: str,
        *,
        project_name: str,
        project_root: object | None = None,
    ) -> KnowledgeEntry | None:
        del project_root
        if not self._store.record_payload_exists("knowledge_entries", entry_id):
            return None
        entry = KnowledgeEntry.from_dict(
            self._store.read_record_payload("knowledge_entries", entry_id)
        )
        return entry if entry.project_name == project_name else None

    async def list_entries(
        self,
        project_name: str,
        *,
        project_root: object | None = None,
    ) -> list[KnowledgeEntry]:
        del project_root
        return sorted(
            (
                KnowledgeEntry.from_dict(payload)
                for payload in self._store.list_record_payloads(
                    "knowledge_entries", project_name=project_name
                )
            ),
            key=lambda entry: (entry.module_path, entry.title, entry.id),
        )

    async def known_projects(self) -> list[str]:
        return sorted(
            {
                str(payload.get("project_name") or "").strip()
                for payload in self._store.list_record_payloads("knowledge_entries")
                if str(payload.get("project_name") or "").strip()
            }
        )

    async def list_sources(self, knowledge_id: str) -> list[KnowledgeSource]:
        return sorted(
            (
                KnowledgeSource.from_dict(payload)
                for payload in self._store.list_record_payloads("knowledge_sources")
                if str(payload.get("knowledge_id") or "") == knowledge_id
            ),
            key=lambda source: (source.source_kind, source.locator, source.id),
        )

    async def render_markdown(
        self,
        project_name: str,
        *,
        include_details: bool = False,
    ) -> str:
        entries = await self.list_entries(project_name)
        source_map = {
            entry.id: await self.list_sources(entry.id) for entry in entries
        }
        return render_knowledge_markdown(
            project_name,
            entries,
            include_details=include_details,
            sources_by_knowledge_id=source_map,
        )

    async def refresh_entry_verification(
        self,
        *,
        project_name: str,
        entry_id: str,
        verified_at: datetime,
        refresh_id: str,
        refreshed_sources: Sequence[KnowledgeSource] | None = None,
    ) -> dict:
        """Record a source-backed freshness check without changing knowledge.

        Dream and Review may prove that a current statement is still supported.
        That is not a semantic rewrite, so it neither creates a new knowledge
        revision nor mutates the statement. The entry and its minimal source
        receipts are nevertheless updated atomically with CAS preconditions.
        """

        current = await self.get_entry(entry_id, project_name=project_name)
        if current is None:
            raise ValueError("knowledge verification target is not current")
        sources = await self.list_sources(entry_id)
        if not sources:
            raise ValueError("knowledge verification refresh requires sources")
        normalized_at = verified_at.astimezone(timezone.utc)
        refreshed_entry = current.model_copy(
            update={"verified_at": normalized_at, "updated_at": normalized_at}
        )
        current_sources_by_id = {source.id: source for source in sources}
        if refreshed_sources is not None:
            proposed_by_id = {source.id: source for source in refreshed_sources}
            if set(proposed_by_id) != set(current_sources_by_id):
                raise ValueError("knowledge verification refresh source set changed")
            for source_id, proposed in proposed_by_id.items():
                current_source = current_sources_by_id[source_id]
                if (
                    proposed.project_name != project_name
                    or proposed.knowledge_id != entry_id
                    or proposed.source_kind != current_source.source_kind
                    or proposed.locator != current_source.locator
                ):
                    raise ValueError("knowledge verification refresh source identity changed")
            refreshed_source_rows = [
                proposed_by_id[source.id].model_copy(update={"verified_at": normalized_at})
                for source in sources
            ]
        else:
            refreshed_source_rows = [
                source.model_copy(update={"verified_at": normalized_at})
                for source in sources
            ]
        operations = [
            _replace_operation(
                self._store,
                "knowledge_entries",
                current.id,
                refreshed_entry.to_dict(),
                project_name=project_name,
            )
        ]
        operations.extend(
            _replace_operation(
                self._store,
                "knowledge_sources",
                source.id,
                source.to_dict(),
                project_name=project_name,
            )
            for source in refreshed_source_rows
        )
        return self._store.apply_canonical_payload_transaction(
            idempotency_key=f"knowledge-verification-refresh:{refresh_id}",
            mutations=operations,
        )

    async def apply_current_change(
        self,
        *,
        candidate_before: KnowledgeCandidate,
        candidate_after: KnowledgeCandidate,
        decision: AssimilationDecision,
        added_entries: Sequence[KnowledgeEntry],
        predecessor_entries: Sequence[KnowledgeEntry],
        source_refs_by_entry: Mapping[
            str, Sequence[ProjectKnowledgeSourceRef]
        ],
        project_root: object | None = None,
    ) -> dict:
        """Atomically add current knowledge or replace current entries."""

        del project_root
        if decision.disposition not in _WRITING_DISPOSITIONS:
            raise ValueError("knowledge change requires add, refine, or replace")
        if decision.candidate_id != candidate_before.id:
            raise ValueError("knowledge change candidate does not match decision")
        if candidate_before.project_name != candidate_after.project_name:
            raise ValueError("knowledge change candidate crosses projects")
        if decision.project_name != candidate_before.project_name:
            raise ValueError("knowledge change decision crosses projects")
        if {entry.id for entry in added_entries} != set(
            decision.canonical_truth_ids
        ):
            raise ValueError("knowledge change output ids do not match decision")
        if {entry.id for entry in predecessor_entries} != set(
            decision.predecessor_truth_ids
        ):
            raise ValueError("knowledge change predecessor ids do not match decision")
        if decision.disposition == "add" and predecessor_entries:
            raise ValueError("add cannot retire current knowledge")
        if decision.disposition in {"refine", "replace"} and not predecessor_entries:
            raise ValueError(
                f"{decision.disposition} requires at least one current knowledge target"
            )

        project_name = decision.project_name
        current_predecessors: list[KnowledgeEntry] = []
        predecessor_sources: dict[str, list[KnowledgeSource]] = {}
        for expected in predecessor_entries:
            current = await self.get_entry(expected.id, project_name=project_name)
            if current is None:
                raise ValueError("knowledge change predecessor is not current")
            if current.to_dict() != expected.to_dict():
                raise ValueError("knowledge change predecessor changed before commit")
            current_predecessors.append(current)
            predecessor_sources[current.id] = await self.list_sources(current.id)

        for entry in added_entries:
            if entry.project_name != project_name:
                raise ValueError("knowledge change output crosses projects")
            if not source_refs_by_entry.get(entry.id):
                raise ValueError("knowledge write requires a real source reference")

        new_sources: list[KnowledgeSource] = []
        for entry in added_entries:
            new_sources.extend(
                _knowledge_sources(entry, source_refs_by_entry[entry.id])
            )

        operations: list[dict] = []
        for entry in current_predecessors:
            for source in predecessor_sources[entry.id]:
                operations.append(
                    _delete_operation(
                        self._store,
                        "knowledge_sources",
                        source.id,
                        project_name=source.project_name,
                    )
                )
            operations.append(
                _delete_operation(
                    self._store,
                    "knowledge_entries",
                    entry.id,
                    project_name=entry.project_name,
                )
            )
        for entry in added_entries:
            operations.append(_new_operation("knowledge_entries", entry.id, entry.to_dict()))
        for source in new_sources:
            operations.append(_new_operation("knowledge_sources", source.id, source.to_dict()))
        return self._store.apply_canonical_payload_transaction(
            idempotency_key=f"knowledge-change:{decision.id}",
            mutations=operations,
        )

    async def current_change_committed(self, decision_id: str) -> bool:
        """Return whether this exact knowledge change already committed."""

        return (
            self._store.canonical_payload_transaction_result(
                f"knowledge-change:{decision_id}"
            )
            is not None
        )

    async def delete_current_entry(
        self,
        *,
        project_name: str,
        entry_id: str,
    ) -> dict:
        """Delete one current entry and its source locators without a history copy."""

        current = await self.get_entry(entry_id, project_name=project_name)
        if current is None:
            return {"deleted": False, "knowledge_id": entry_id}
        sources = await self.list_sources(current.id)
        operations: list[dict] = []
        for source in sources:
            operations.append(
                _delete_operation(
                    self._store,
                    "knowledge_sources",
                    source.id,
                    project_name=source.project_name,
                )
            )
        operations.append(
            _delete_operation(
                self._store,
                "knowledge_entries",
                current.id,
                project_name=current.project_name,
            )
        )
        result = self._store.apply_canonical_payload_transaction(
            idempotency_key=(
                f"knowledge-delete:{project_name}:{entry_id}:"
                f"{current.updated_at.isoformat()}"
            ),
            mutations=operations,
        )
        return {**result, "deleted": True, "knowledge_id": entry_id}

    async def save_candidate(self, candidate: KnowledgeCandidate) -> str:
        return self._workspace.save_candidate(candidate)

    async def get_candidate(self, candidate_id: str) -> KnowledgeCandidate | None:
        return self._workspace.get_candidate(candidate_id)

    async def list_candidates(self, project_name: str) -> list[KnowledgeCandidate]:
        return self._workspace.list_candidates(project_name)

    async def save_evidence(self, evidence: KnowledgeEvidence) -> str:
        return self._workspace.save_evidence(evidence)

    async def list_evidence(self, candidate_id: str) -> list[KnowledgeEvidence]:
        return self._workspace.list_evidence(candidate_id)

    async def save_decision(
        self,
        decision: AssimilationDecision,
        *,
        project_root: object | None = None,
    ) -> str:
        del project_root
        if decision.disposition in _UNRESOLVED_DISPOSITIONS:
            return self._workspace.save_unresolved_decision(decision)
        # Successful/non-writing decisions are already represented in the
        # Answer Packet and terminal job receipt. They deliberately do not
        # become a permanent decision ledger.
        return decision.id

    async def get_decision(self, decision_id: str) -> AssimilationDecision | None:
        return self._workspace.get_unresolved_decision(decision_id)

    async def list_decisions(self, candidate_id: str) -> list[AssimilationDecision]:
        return [
            item
            for item in self._workspace.list_unresolved_decisions()
            if item.candidate_id == candidate_id
        ]

    async def list_all_decisions(self) -> list[AssimilationDecision]:
        return self._workspace.list_unresolved_decisions()

    async def cleanup_candidate(self, candidate_id: str) -> None:
        self._workspace.cleanup_candidate(candidate_id)

    async def cleanup_job(self, distill_job_id: str) -> int:
        return self._workspace.cleanup_workspace(distill_job_id)

    async def prune_expired_work(self, *, ttl_seconds: int) -> int:
        return self._workspace.prune_expired(ttl_seconds=ttl_seconds)

def _knowledge_sources(
    entry: KnowledgeEntry,
    refs: Sequence[ProjectKnowledgeSourceRef],
) -> list[KnowledgeSource]:
    verified_at = entry.verified_at or entry.updated_at
    sources: list[KnowledgeSource] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        parsed = urlparse(ref.target)
        source_kind = str(ref.kind or "").strip()
        if not source_kind:
            source_kind = "repository" if parsed.scheme == "file" and not parsed.fragment else "transcript"
        source_key = (source_kind, ref.target)
        if source_key in seen:
            continue
        seen.add(source_key)
        identity = f"{entry.id}\0{source_kind}\0{ref.target}"
        sources.append(
            KnowledgeSource(
                id=str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge-source:{identity}")),
                knowledge_id=entry.id,
                project_name=entry.project_name,
                source_kind=source_kind,
                locator=ref.target,
                content_sha256=ref.digest,
                verified_at=verified_at,
            )
        )
    return sources


def _new_operation(collection: str, entity_id: str, payload: dict) -> dict:
    return {
        "operation": "upsert",
        "collection": collection,
        "entity_id": entity_id,
        "payload": payload,
        "expected_sha256": None,
    }


def _replace_operation(
    store: LocalStructuredStore,
    collection: str,
    entity_id: str,
    payload: dict,
    *,
    project_name: str,
) -> dict:
    expected = store.record_payload_sha256(
        collection,
        entity_id,
        project_name=project_name,
    )
    if expected is None:
        raise ValueError(f"current {collection} record is missing: {entity_id}")
    return {
        "operation": "upsert",
        "collection": collection,
        "entity_id": entity_id,
        "payload": payload,
        "project_name": project_name,
        "expected_sha256": expected,
    }


def _delete_operation(
    store: LocalStructuredStore,
    collection: str,
    entity_id: str,
    *,
    project_name: str,
) -> dict:
    digest = store.record_payload_sha256(
        collection, entity_id, project_name=project_name
    )
    if digest is None:
        raise ValueError(f"current {collection} record is missing: {entity_id}")
    return {
        "operation": "delete",
        "collection": collection,
        "entity_id": entity_id,
        "project_name": project_name,
        "expected_sha256": digest,
    }


__all__ = ["KnowledgeStore"]
