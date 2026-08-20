"""SQLite-authoritative current knowledge and finite job processing state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    KnowledgeMutation,
    KnowledgeSource,
    KnowledgeVersion,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.knowledge_renderer import render_knowledge_markdown
from harness_mem.storage.knowledge_job_workspace import KnowledgeJobWorkspace

if TYPE_CHECKING:
    from harness_mem.storage.local_structured_store import LocalStructuredStore


_WRITING_DISPOSITIONS = {"add", "refine", "supersede"}
_UNRESOLVED_DISPOSITIONS = {"defer", "conflict"}
_MAX_UNDO_MUTATIONS_PER_PROJECT = 32


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

    async def apply_truth_mutation(
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
        """Commit one add/refine/supersede atomically in canonical SQLite."""

        del project_root
        if decision.disposition not in _WRITING_DISPOSITIONS:
            raise ValueError("truth mutation requires add, refine, or supersede")
        if decision.candidate_id != candidate_before.id:
            raise ValueError("knowledge mutation candidate does not match decision")
        if candidate_before.project_name != candidate_after.project_name:
            raise ValueError("knowledge mutation candidate crosses projects")
        if decision.project_name != candidate_before.project_name:
            raise ValueError("knowledge mutation decision crosses projects")
        if {entry.id for entry in added_entries} != set(
            decision.canonical_truth_ids
        ):
            raise ValueError("knowledge mutation output ids do not match decision")
        if {entry.id for entry in predecessor_entries} != set(
            decision.predecessor_truth_ids
        ):
            raise ValueError("knowledge mutation predecessor ids do not match decision")
        if decision.disposition == "add" and predecessor_entries:
            raise ValueError("add cannot retire current knowledge")
        if decision.disposition in {"refine", "supersede"} and len(
            predecessor_entries
        ) != 1:
            raise ValueError(
                f"{decision.disposition} requires one current knowledge target"
            )

        existing_mutation = await self.get_mutation(decision.id)
        if existing_mutation is not None:
            expected_current = [entry.id for entry in added_entries]
            if (
                existing_mutation.project_name != decision.project_name
                or existing_mutation.disposition != decision.disposition
                or existing_mutation.current_knowledge_ids != expected_current
                or existing_mutation.reverses_mutation_id
                != decision.reverses_decision_id
            ):
                raise ValueError(
                    "knowledge mutation id was already committed for different work"
                )
            return {
                "idempotency_key": f"knowledge-mutation:{decision.id}",
                "mutation_count": 0,
                "mutations": [],
                "replayed": True,
            }

        project_name = decision.project_name
        current_predecessors: list[KnowledgeEntry] = []
        predecessor_sources: dict[str, list[KnowledgeSource]] = {}
        for expected in predecessor_entries:
            current = await self.get_entry(expected.id, project_name=project_name)
            if current is None:
                raise ValueError("knowledge mutation predecessor is not current")
            if current.to_dict() != expected.to_dict():
                raise ValueError("knowledge mutation predecessor changed before commit")
            current_predecessors.append(current)
            predecessor_sources[current.id] = await self.list_sources(current.id)

        for entry in added_entries:
            if entry.project_name != project_name:
                raise ValueError("knowledge mutation output crosses projects")
            if not source_refs_by_entry.get(entry.id):
                raise ValueError("knowledge write requires a real source reference")

        versions = [
            _version_snapshot(
                decision.id,
                entry,
                predecessor_sources.get(entry.id, []),
            )
            for entry in current_predecessors
        ]
        mutation = KnowledgeMutation(
            id=decision.id,
            project_name=project_name,
            disposition=cast(
                Literal["add", "refine", "supersede"], decision.disposition
            ),
            current_knowledge_ids=[entry.id for entry in added_entries],
            predecessor_version_ids=[version.id for version in versions],
            reverses_mutation_id=decision.reverses_decision_id,
            reason=decision.reason,
            recorded_at=decision.decided_at,
        )
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
        for version in versions:
            operations.append(_new_operation("knowledge_versions", version.id, version.to_dict()))
        for entry in added_entries:
            operations.append(_new_operation("knowledge_entries", entry.id, entry.to_dict()))
        for source in new_sources:
            operations.append(_new_operation("knowledge_sources", source.id, source.to_dict()))
        operations.append(
            _new_operation("knowledge_mutations", mutation.id, mutation.to_dict())
        )
        operations.extend(
            await self._undo_retention_operations(
                project_name=project_name,
                incoming=mutation,
            )
        )
        return self._store.apply_canonical_payload_transaction(
            idempotency_key=f"knowledge-mutation:{decision.id}",
            mutations=operations,
        )

    async def archive_current_entry(
        self,
        *,
        project_name: str,
        entry_id: str,
        mutation_id: str,
        reason: str,
    ) -> dict:
        """Remove one obsolete current entry while retaining a reversible snapshot.

        This is a maintenance-only mutation for an already governed truth. It
        never hard-deletes the entry's prior version or sources, and a later
        ``undo_truth_mutation`` restores the exact entry from this snapshot.
        """

        normalized_reason = str(reason).strip()
        if not normalized_reason:
            raise ValueError("knowledge archive requires a reason")
        current = await self.get_entry(entry_id, project_name=project_name)
        existing = await self.get_mutation(mutation_id)
        if existing is not None:
            if (
                existing.project_name != project_name
                or existing.disposition != "archive"
                or existing.current_knowledge_ids
            ):
                raise ValueError(
                    "knowledge archive mutation id was already committed for different work"
                )
            return {
                "idempotency_key": f"knowledge-mutation:{mutation_id}",
                "mutation_count": 0,
                "mutations": [],
                "replayed": True,
            }
        if current is None:
            raise ValueError("knowledge archive target is not current")
        sources = await self.list_sources(current.id)
        version = _version_snapshot(mutation_id, current, sources)
        mutation = KnowledgeMutation(
            id=mutation_id,
            project_name=project_name,
            disposition="archive",
            current_knowledge_ids=[],
            predecessor_version_ids=[version.id],
            reason=normalized_reason,
        )
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
        operations.append(_new_operation("knowledge_versions", version.id, version.to_dict()))
        operations.append(
            _new_operation("knowledge_mutations", mutation.id, mutation.to_dict())
        )
        operations.extend(
            await self._undo_retention_operations(
                project_name=project_name,
                incoming=mutation,
            )
        )
        return self._store.apply_canonical_payload_transaction(
            idempotency_key=f"knowledge-mutation:{mutation_id}",
            mutations=operations,
        )

    async def undo_truth_mutation(
        self,
        *,
        mutation_id: str,
        reversal_id: str,
    ) -> dict[str, list[str] | str]:
        """Undo one current mutation using only bounded durable version state."""

        mutation = await self.get_mutation(mutation_id)
        if mutation is None:
            raise ValueError("knowledge mutation is missing")
        if any(
            item.reverses_mutation_id == mutation.id
            for item in await self.list_mutations(mutation.project_name)
        ):
            raise ValueError("knowledge mutation has already been undone")
        for later in await self.list_mutations(mutation.project_name):
            if later.id == mutation.id or later.reverses_mutation_id is not None:
                continue
            for version_id in later.predecessor_version_ids:
                version = await self.get_version(version_id)
                if (
                    version is not None
                    and version.knowledge_id in mutation.current_knowledge_ids
                ):
                    raise ValueError(
                        "knowledge mutation has a later replacement; undo it first"
                    )

        retired: list[KnowledgeEntry] = []
        retired_sources: dict[str, list[KnowledgeSource]] = {}
        for entry_id in mutation.current_knowledge_ids:
            entry = await self.get_entry(entry_id, project_name=mutation.project_name)
            if entry is None:
                raise ValueError("knowledge undo target is no longer current")
            retired.append(entry)
            retired_sources[entry.id] = await self.list_sources(entry.id)

        predecessor_versions = [
            await self.get_version(version_id)
            for version_id in mutation.predecessor_version_ids
        ]
        if any(version is None for version in predecessor_versions):
            raise ValueError("knowledge undo predecessor snapshot is incomplete")
        restored: list[KnowledgeEntry] = []
        restored_sources: list[KnowledgeSource] = []
        now = _utc_now()
        for version in predecessor_versions:
            assert version is not None
            restored.append(
                KnowledgeEntry(
                    id=version.knowledge_id,
                    project_name=version.project_name,
                    module_path=list(version.module_path),
                    title=version.title,
                    statement=version.statement,
                    verified_at=version.verified_at,
                    revision=version.revision + 1,
                    created_at=now,
                    updated_at=now,
                )
            )
            restored_sources.extend(version.sources)

        retired_versions = [
            _version_snapshot(reversal_id, entry, retired_sources[entry.id])
            for entry in retired
        ]
        reversal = KnowledgeMutation(
            id=reversal_id,
            project_name=mutation.project_name,
            disposition=mutation.disposition,
            current_knowledge_ids=[entry.id for entry in restored],
            predecessor_version_ids=[item.id for item in retired_versions],
            reverses_mutation_id=mutation.id,
            reason=f"undo: {mutation.reason}"[:2000],
        )
        operations: list[dict] = []
        for entry in retired:
            for source in retired_sources[entry.id]:
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
        for version in retired_versions:
            operations.append(_new_operation("knowledge_versions", version.id, version.to_dict()))
        for entry in restored:
            operations.append(_new_operation("knowledge_entries", entry.id, entry.to_dict()))
        for source in restored_sources:
            operations.append(_new_operation("knowledge_sources", source.id, source.to_dict()))
        operations.append(
            _new_operation("knowledge_mutations", reversal.id, reversal.to_dict())
        )
        operations.extend(
            await self._undo_retention_operations(
                project_name=mutation.project_name,
                incoming=reversal,
            )
        )
        self._store.apply_canonical_payload_transaction(
            idempotency_key=f"knowledge-mutation:{reversal.id}",
            mutations=operations,
        )
        return {
            "mutation_id": mutation.id,
            "reversal_id": reversal.id,
            "restored_knowledge_ids": [entry.id for entry in restored],
            "retired_knowledge_ids": [entry.id for entry in retired],
        }

    async def get_version(self, version_id: str) -> KnowledgeVersion | None:
        if not self._store.record_payload_exists("knowledge_versions", version_id):
            return None
        return KnowledgeVersion.from_dict(
            self._store.read_record_payload("knowledge_versions", version_id)
        )

    async def list_versions(self, project_name: str) -> list[KnowledgeVersion]:
        return sorted(
            (
                KnowledgeVersion.from_dict(payload)
                for payload in self._store.list_record_payloads(
                    "knowledge_versions", project_name=project_name
                )
            ),
            key=lambda item: (item.recorded_at, item.id),
        )

    async def get_mutation(self, mutation_id: str) -> KnowledgeMutation | None:
        if not self._store.record_payload_exists("knowledge_mutations", mutation_id):
            return None
        return KnowledgeMutation.from_dict(
            self._store.read_record_payload("knowledge_mutations", mutation_id)
        )

    async def list_mutations(self, project_name: str) -> list[KnowledgeMutation]:
        return sorted(
            (
                KnowledgeMutation.from_dict(payload)
                for payload in self._store.list_record_payloads(
                    "knowledge_mutations", project_name=project_name
                )
            ),
            key=lambda item: (item.recorded_at, item.id),
        )

    async def _undo_retention_operations(
        self,
        *,
        project_name: str,
        incoming: KnowledgeMutation,
    ) -> list[dict]:
        """Bound durable Review undo to the newest project mutations."""

        mutations = [
            item
            for item in await self.list_mutations(project_name)
            if item.id != incoming.id
        ]
        mutations.append(incoming)
        mutations.sort(key=lambda item: (item.recorded_at, item.id))
        kept = mutations[-_MAX_UNDO_MUTATIONS_PER_PROJECT:]
        removed = mutations[:-_MAX_UNDO_MUTATIONS_PER_PROJECT]
        if not removed:
            return []
        kept_version_ids = {
            version_id for item in kept for version_id in item.predecessor_version_ids
        }
        operations: list[dict] = []
        for item in removed:
            if self._store.record_payload_exists("knowledge_mutations", item.id):
                operations.append(
                    _delete_operation(
                        self._store,
                        "knowledge_mutations",
                        item.id,
                        project_name=item.project_name,
                    )
                )
            for version_id in item.predecessor_version_ids:
                if (
                    version_id not in kept_version_ids
                    and self._store.record_payload_exists(
                        "knowledge_versions", version_id
                    )
                ):
                    operations.append(
                        _delete_operation(
                            self._store,
                            "knowledge_versions",
                            version_id,
                            project_name=item.project_name,
                        )
                    )
        return operations

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
        unresolved = self._workspace.get_unresolved_decision(decision_id)
        if unresolved is not None:
            return unresolved
        mutation = await self.get_mutation(decision_id)
        if mutation is None:
            return None
        versions = [
            await self.get_version(version_id)
            for version_id in mutation.predecessor_version_ids
        ]
        predecessor_entries = [
            KnowledgeEntry(
                id=version.knowledge_id,
                project_name=version.project_name,
                module_path=list(version.module_path),
                title=version.title,
                statement=version.statement,
                verified_at=version.verified_at,
                revision=version.revision,
            )
            for version in versions
            if version is not None
        ]
        return AssimilationDecision(
            id=mutation.id,
            project_name=mutation.project_name,
            candidate_id=f"expired:{mutation.id}",
            disposition=mutation.disposition,
            canonical_truth_ids=list(mutation.current_knowledge_ids),
            predecessor_truth_ids=[entry.id for entry in predecessor_entries],
            predecessor_entries=predecessor_entries,
            reverses_decision_id=mutation.reverses_mutation_id,
            reason=mutation.reason or "bounded durable mutation lineage",
            decided_at=mutation.recorded_at,
        )

    async def list_decisions(self, candidate_id: str) -> list[AssimilationDecision]:
        return [
            item
            for item in self._workspace.list_unresolved_decisions()
            if item.candidate_id == candidate_id
        ]

    async def list_all_decisions(self) -> list[AssimilationDecision]:
        unresolved = self._workspace.list_unresolved_decisions()
        mutations = []
        for project_name in await self.known_projects():
            for mutation in await self.list_mutations(project_name):
                decision = await self.get_decision(mutation.id)
                if decision is not None:
                    mutations.append(decision)
        return [*unresolved, *mutations]

    async def cleanup_candidate(self, candidate_id: str) -> None:
        self._workspace.cleanup_candidate(candidate_id)

    async def cleanup_job(self, distill_job_id: str) -> int:
        return self._workspace.cleanup_workspace(distill_job_id)

    async def prune_expired_work(self, *, ttl_seconds: int) -> int:
        return self._workspace.prune_expired(ttl_seconds=ttl_seconds)

    async def recover_staged_mutations(self) -> None:
        """Compatibility no-op: SQLite transactions require no cross-file recovery."""


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


def _version_snapshot(
    mutation_id: str,
    entry: KnowledgeEntry,
    sources: Sequence[KnowledgeSource],
) -> KnowledgeVersion:
    return KnowledgeVersion(
        id=str(
            uuid5(
                NAMESPACE_URL,
                f"harness-mem:knowledge-version:{mutation_id}:{entry.id}:{entry.revision}",
            )
        ),
        knowledge_id=entry.id,
        project_name=entry.project_name,
        revision=entry.revision,
        module_path=list(entry.module_path),
        title=entry.title,
        statement=entry.statement,
        verified_at=entry.verified_at,
        sources=list(sources),
    )


def _new_operation(collection: str, entity_id: str, payload: dict) -> dict:
    return {
        "operation": "upsert",
        "collection": collection,
        "entity_id": entity_id,
        "payload": payload,
        "expected_sha256": None,
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
