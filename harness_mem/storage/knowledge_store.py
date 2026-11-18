"""SQLite-authoritative current knowledge and finite job processing state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    KnowledgeSource,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import (
    ReportOmission,
    ReportOutputProposal,
    SourceReport,
    account_write_allowed,
    bind_report_split,
    report_revision_allowed,
)
from harness_mem.knowledge_renderer import render_knowledge_markdown
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
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
        expected_entry: KnowledgeEntry | None = None,
        expected_sources: Sequence[KnowledgeSource] | None = None,
    ) -> dict:
        """Record a source-backed freshness check without changing knowledge.

        Dream and Review may prove that a current statement is still supported.
        That is not a semantic rewrite, so it neither creates a new knowledge
        revision nor mutates the statement. The entry and its minimal source
        receipts are nevertheless updated atomically with CAS preconditions.
        """

        expected_sha = self._store.record_payload_sha256("knowledge_entries", entry_id)
        source_hashes = (
            {source.id: self._store.record_payload_sha256("knowledge_sources", source.id)
             for source in expected_sources}
            if expected_sources is not None else None
        )
        current = await self.get_entry(entry_id, project_name=project_name)
        if expected_entry is not None and (
            current is None or current.to_dict() != expected_entry.to_dict()
        ):
            raise CanonicalTransactionPreconditionError("confirmation target changed after verification")
        if current is None:
            raise ValueError("knowledge verification target is not current")
        sources = await self.list_sources(entry_id)
        if not sources:
            raise ValueError("knowledge verification refresh requires sources")
        if expected_sources is not None:
            expected_by_id = {source.id: source for source in expected_sources}
            if (len(expected_by_id) != len(expected_sources)
                    or {source.id for source in sources} != set(expected_by_id)
                    or any(source.to_dict() != expected_by_id[source.id].to_dict()
                           for source in sources)
                    or any(value is None for value in source_hashes.values())):
                raise CanonicalTransactionPreconditionError(
                    "confirmation sources changed after verification")
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
        operations[0]["expected_sha256"] = expected_sha
        if source_hashes is not None:
            operations[0]["expected_source_ids"] = sorted(source_hashes)
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
        if source_hashes is not None:
            for operation in operations[1:]:
                operation["expected_sha256"] = source_hashes[operation["entity_id"]]
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
        expected_context_entries: Sequence[KnowledgeEntry] = (),
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
        context_hashes: dict[str, str] = {}
        for expected in expected_context_entries:
            if expected.project_name != project_name or expected.id in context_hashes:
                raise CanonicalTransactionPreconditionError("knowledge context expectation scope changed")
            # Capture the hash before reading the object. A concurrent change
            # either fails the object comparison or the transaction's assert.
            digest = self._store.record_payload_sha256(
                "knowledge_entries", expected.id, project_name=project_name,
            )
            current = await self.get_entry(expected.id, project_name=project_name)
            if digest is None or current is None or current.to_dict() != expected.to_dict():
                raise CanonicalTransactionPreconditionError("knowledge context changed after verification")
            context_hashes[expected.id] = digest
        current_predecessors: list[KnowledgeEntry] = []
        predecessor_sources: dict[str, list[KnowledgeSource]] = {}
        predecessor_hashes: dict[str, str] = {}
        predecessor_source_hashes: dict[str, str] = {}
        for expected in predecessor_entries:
            digest = self._store.record_payload_sha256(
                "knowledge_entries", expected.id, project_name=project_name,
            )
            current = await self.get_entry(expected.id, project_name=project_name)
            if digest is None or current is None:
                raise ValueError("knowledge change predecessor is not current")
            if current.to_dict() != expected.to_dict():
                raise ValueError("knowledge change predecessor changed before commit")
            current_predecessors.append(current)
            predecessor_hashes[current.id] = digest
            predecessor_sources[current.id] = await self.list_sources(current.id)
            for source in predecessor_sources[current.id]:
                source_digest = self._store.record_payload_sha256(
                    "knowledge_sources", source.id, project_name=project_name,
                )
                if source_digest is None or KnowledgeSource.from_dict(
                    self._store.read_record_payload("knowledge_sources", source.id)
                ).to_dict() != source.to_dict():
                    raise CanonicalTransactionPreconditionError("knowledge source changed before commit")
                predecessor_source_hashes[source.id] = source_digest

        split_entries: list[KnowledgeEntry] = []
        for entry in added_entries:
            if entry.project_name != project_name:
                raise ValueError("knowledge change output crosses projects")
            if not source_refs_by_entry.get(entry.id):
                raise ValueError("knowledge write requires a real source reference")
            refs = source_refs_by_entry[entry.id]
            report = entry.source_report
            if any(ref.kind == "source_report" for ref in refs) != (report is not None):
                raise ValueError("source-report and fact authority boundary cannot be crossed")
            if report is not None and decision.report_split:
                split_entries.append(entry)
            elif report is not None:
                predecessor_reports = [
                    old.source_report
                    for old in predecessor_entries
                    if old.source_report is not None
                ]
                topic_judgments = list(decision.report_topic_judgments)
                if topic_judgments:
                    if (candidate_before.source_report is None or decision.report_topic_judgment is not None
                            or len(topic_judgments) != len(predecessor_entries)
                            or len(predecessor_reports) != len(predecessor_entries)):
                        raise ValueError("source-report topic judgments must cover every predecessor once")
                    expected_report = candidate_before.source_report.with_topic_revision(
                        report.render_title(), topic_judgments[0], predecessor=predecessor_reports[0])
                    if expected_report != report or any(
                        not judgment.authorizes(predecessor, report)
                        for predecessor, judgment in zip(predecessor_reports, topic_judgments)
                    ):
                        raise ValueError("source-report replacement topic judgments changed before commit")
                elif len(predecessor_reports) > 1:
                    raise ValueError("source-report topic judgments must cover every predecessor once")
                elif (candidate_before.source_report is None
                        or not account_write_allowed(
                            candidate_before.source_report,
                            report,
                            decision.report_topic_judgment,
                            predecessor_reports,
                        )):
                    raise ValueError("source-report write must retain its verified candidate account")
                if not topic_judgments and any(
                    old.source_report is None
                    or not report_revision_allowed(
                        report,
                        old.source_report,
                        decision.report_topic_judgment,
                        disposition=decision.disposition,
                    )
                    for old in predecessor_entries
                ):
                    raise ValueError(
                        "source-report replacement cannot cross source, speaker, period, or topic"
                    )
            if report is not None:
                indexes: set[int] = set()
                for ref in refs:
                    query = parse_qs(urlparse(ref.target).fragment)
                    if (ref.kind != "source_report"
                            or query.get("source_id") != [report.source_id]
                            or query.get("source_revision") != [report.source_revision]
                            or query.get("role") != [report.speaker]
                            or len(query.get("exchange", [])) != 1):
                        raise ValueError("source-report authority does not match retained source scope")
                    try:
                        indexes.add(int(query["exchange"][0]))
                    except ValueError as exc:
                        raise ValueError("source-report exchange is invalid") from exc
                if indexes != set(report.exchange_indexes):
                    raise ValueError("source-report exchanges do not match retained source scope")
            if any((predecessor.source_report is None) != (report is None)
                   for predecessor in predecessor_entries):
                raise ValueError("source-report and fact authority boundary cannot be crossed")
        if decision.report_split:
            if not split_entries or len(predecessor_entries) != 1:
                raise ValueError("a report refinement replaces one predecessor with retained outputs")
            predecessor_report = predecessor_entries[0].source_report
            if (
                candidate_before.source_report is None
                or predecessor_report is None
                or candidate_before.source_report != predecessor_report
            ):
                raise ValueError("source-report write must retain its verified candidate account")
            payload = decision.report_split
            bound = bind_report_split(
                candidate_before.source_report,
                original_support=str(payload.get("original_support") or ""),
                outputs=[ReportOutputProposal.model_validate(item) for item in payload.get("outputs") or []],
                omissions=[ReportOmission.model_validate(item) for item in payload.get("omissions") or []],
                mode=str(payload.get("mode", "literal_projection")),
            )
            written = [entry.source_report for entry in split_entries]
            if any(not isinstance(item, SourceReport) for item in written) or written != bound:
                raise ValueError("stored report split does not match its bound outputs")

        new_sources: list[KnowledgeSource] = []
        for entry in added_entries:
            new_sources.extend(
                _knowledge_sources(entry, source_refs_by_entry[entry.id])
            )

        operations: list[dict] = []
        retiring_ids = {entry.id for entry in current_predecessors}
        output_ids = {entry.id for entry in added_entries}
        for identity, digest in context_hashes.items():
            if identity in retiring_ids:
                continue  # Its existing deletion carries this same guard below.
            if identity in output_ids:
                raise CanonicalTransactionPreconditionError("knowledge output overlaps retained context")
            operations.append({
                "operation": "assert", "collection": "knowledge_entries",
                "entity_id": identity, "project_name": project_name,
                "expected_sha256": digest,
            })
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
            operations[-1]["expected_sha256"] = context_hashes.get(entry.id, predecessor_hashes[entry.id])
            operations[-1]["expected_source_ids"] = sorted(source.id for source in predecessor_sources[entry.id])
        # A content-derived successor can retain a predecessor's identity.
        # Replace its guarded deletion with one guarded upsert, including any
        # retained source identity; the canonical transaction still rejects
        # every other attempt to mutate one target twice.
        retired_positions = {
            (operation["collection"], operation["entity_id"]): index
            for index, operation in enumerate(operations) if operation["operation"] == "delete"
        }
        for operation in operations:
            if operation["operation"] == "delete" and operation["collection"] == "knowledge_sources":
                operation["expected_sha256"] = predecessor_source_hashes[operation["entity_id"]]

        def add_output(collection: str, identity: str, payload: dict) -> None:
            position = retired_positions.pop((collection, identity), None)
            if position is None:
                operations.append(_new_operation(collection, identity, payload))
            else:
                operations[position] = {**operations[position], "operation": "upsert", "payload": payload}

        for entry in added_entries:
            add_output("knowledge_entries", entry.id, entry.to_dict())
        for source in new_sources:
            add_output("knowledge_sources", source.id, source.to_dict())
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
        expected_entry: KnowledgeEntry | None = None,
        retained_entries: Sequence[KnowledgeEntry] = (),
    ) -> dict:
        """Delete one current entry and its source locators without a history copy."""

        expected_sha = self._store.record_payload_sha256("knowledge_entries", entry_id)
        current = await self.get_entry(entry_id, project_name=project_name)
        if expected_entry is not None and (
            current is None or current.to_dict() != expected_entry.to_dict()
        ):
            raise CanonicalTransactionPreconditionError("delete target changed after verification")
        if current is None:
            return {"deleted": False, "knowledge_id": entry_id}
        sources = await self.list_sources(current.id)
        operations: list[dict] = []
        for retained in retained_entries:
            retained_sha = self._store.record_payload_sha256("knowledge_entries", retained.id)
            retained_current = await self.get_entry(retained.id, project_name=project_name)
            if retained_current is None or retained_current.to_dict() != retained.to_dict():
                raise CanonicalTransactionPreconditionError("retained knowledge changed after verification")
            operations.append({
                "operation": "assert", "collection": "knowledge_entries",
                "entity_id": retained.id, "project_name": retained.project_name,
                "expected_sha256": retained_sha,
            })
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
        operations[-1]["expected_sha256"] = expected_sha
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
    source_indexes: dict[tuple[str, str], int] = {}
    for ref in refs:
        parsed = urlparse(ref.target)
        source_kind = str(ref.kind or "").strip()
        if not source_kind:
            source_kind = "repository" if parsed.scheme == "file" and not parsed.fragment else "transcript"
        source_key = (source_kind, ref.target)
        if source_key in source_indexes:
            existing = sources[source_indexes[source_key]]
            if ref.digest == existing.content_sha256:
                existing.bindings.extend(binding for binding in ref.bindings if binding not in existing.bindings)
            continue
        source_indexes[source_key] = len(sources)
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
                bindings=ref.bindings,
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
