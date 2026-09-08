"""Write verified candidate decisions to the current knowledge repository."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence, cast
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeCandidateStatus,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.commands.evidence_admission import (
    validate_candidate_evidence,
    validate_knowledge_sources,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def record_assimilation_result(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    point: Mapping[str, Any],
    project_root: str | Path | None = None,
    source_refs: Sequence[ProjectKnowledgeSourceRef] = (),
) -> list[str]:
    """Write clean current entries for one verified point."""

    store = backend.structured_store.knowledge_store
    candidate_before = candidate.model_copy(deep=True)
    disposition = _disposition(point)
    if disposition in {"add", "refine", "replace", "confirm"} and (
        project_root is None or not source_refs
    ):
        resolved_root, resolved_refs, resolved_verified_at = (
            await resolve_candidate_source_context(
                backend,
                candidate=candidate,
                evidence_items=await store.list_evidence(candidate.id),
                project_root=project_root,
            )
        )
        project_root = resolved_root
        if not source_refs:
            source_refs = resolved_refs
        if point.get("verified_at") is None and resolved_verified_at is not None:
            point = {**point, "verified_at": resolved_verified_at}
    knowledge_ids: list[str] = []
    matched_truth_ids = [str(item) for item in point.get("matched_truth_ids") or []]
    predecessor_truth_ids: list[str] = []
    predecessor_entries: list[KnowledgeEntry] = []
    new_entries: list[KnowledgeEntry] = []
    decision_id: str | None = None
    if disposition in {"add", "refine", "replace"}:
        for _index, item in enumerate(_knowledge_items(point), 1):
            if not source_refs:
                raise ValueError("knowledge write requires a real source reference")
            identity = "\0".join(
                [
                    candidate.project_name,
                    *item["topic_path"],
                    item["title"],
                    item["statement"],
                ]
            )
            entry = KnowledgeEntry(
                id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"harness-mem:knowledge:{identity}",
                    )
                ),
                project_name=candidate.project_name,
                title=item["title"],
                statement=item["statement"],
                module_path=item["topic_path"],
                verified_at=(
                    point.get("verified_at")
                    or getattr(candidate, "verified_at", None)
                ),
            )
            new_entries.append(entry)
            knowledge_ids.append(entry.id)
        decision_id = assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=matched_truth_ids,
            reason=str(point.get("reason", "")),
        )
        if await store.current_change_committed(decision_id):
            current_entries_match = await _current_entries_match(
                store,
                project_name=candidate.project_name,
                expected_entries=new_entries,
            )
            predecessor_still_current = False
            for entry_id in matched_truth_ids:
                if await store.get_entry(
                    entry_id,
                    project_name=candidate.project_name,
                ) is not None:
                    predecessor_still_current = True
                    break
            if not current_entries_match or predecessor_still_current:
                raise RuntimeError(
                    "committed knowledge change no longer matches current knowledge"
                )
            await _verify_normal_search_after_truth_write(
                backend,
                project_name=candidate.project_name,
                project_root=_required_project_root(project_root),
                added_entries=new_entries,
                predecessor_entries=[],
            )
            candidate.status = _separated_status(disposition)
            await store.save_candidate(candidate)
            return knowledge_ids
        if disposition in {"refine", "replace"}:
            missing_target_ids: list[str] = []
            for target_id in matched_truth_ids:
                target = await store.get_entry(
                    target_id,
                    project_name=candidate.project_name,
                    project_root=project_root,
                )
                if target is None:
                    missing_target_ids.append(target_id)
                    continue
                predecessor_truth_ids.append(target.id)
                predecessor_entries.append(target)
            if missing_target_ids:
                raise ValueError(
                    "assimilation replacement target is not current knowledge"
                )
            if len(predecessor_entries) == 1 and any(
                entry.project_name == predecessor.project_name
                and entry.module_path == predecessor.module_path
                and entry.title == predecessor.title
                and entry.statement == predecessor.statement
                for entry in new_entries
                for predecessor in predecessor_entries
            ):
                raise ValueError(
                    f"{disposition} replacement is identical to current knowledge; "
                    "use confirm"
                )
    elif disposition == "confirm":
        knowledge_ids = [
            target_id
            for target_id in matched_truth_ids
            if await store.get_entry(
                target_id,
                project_name=candidate.project_name,
                project_root=project_root,
            )
            is not None
        ]
        if len(knowledge_ids) != 1:
            raise ValueError("confirm target is no longer current project knowledge")

    candidate.status = _separated_status(disposition)
    decision = AssimilationDecision(
        id=decision_id
        or assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=matched_truth_ids,
            reason=str(point.get("reason", "")),
        ),
        project_name=candidate.project_name,
        candidate_id=candidate.id,
        disposition=disposition,
        canonical_truth_ids=knowledge_ids,
        predecessor_truth_ids=predecessor_truth_ids,
        predecessor_entries=predecessor_entries,
        reason=str(point.get("reason") or disposition),
    )
    if new_entries:
        await store.apply_current_change(
            project_root=_required_project_root(project_root),
            candidate_before=candidate_before,
            candidate_after=candidate,
            decision=decision,
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
            source_refs_by_entry={
                entry.id: list(source_refs) for entry in new_entries
            },
        )
        await _verify_normal_search_after_truth_write(
            backend,
            project_name=candidate.project_name,
            project_root=_required_project_root(project_root),
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
        )
        # The SQLite truth transaction is the commit point.  Persisting a
        # terminal workspace status before it succeeds would make a retry skip
        # a candidate whose durable knowledge was never written.
        await store.save_candidate(candidate)
    else:
        await store.save_candidate(candidate)
        await store.save_decision(decision, project_root=project_root)
    return knowledge_ids


async def _verify_normal_search_after_truth_write(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path | None,
    added_entries: Sequence[KnowledgeEntry],
    predecessor_entries: Sequence[KnowledgeEntry],
) -> None:
    """Require the ordinary search path to observe the committed mutation."""

    from harness_mem.read_knowledge import search_current_knowledge

    for entry in added_entries:
        results = await search_current_knowledge(
            backend,
            project_name=project_name,
            query=entry.statement,
            limit=100000,
            project_root=project_root,
        )
        if not any(item.id == entry.id for item in results):
            raise RuntimeError(
                "current knowledge write is not readable through normal search"
            )
    for predecessor in predecessor_entries:
        results = await search_current_knowledge(
            backend,
            project_name=project_name,
            query=predecessor.statement,
            limit=100000,
            project_root=project_root,
        )
        if any(item.id == predecessor.id for item in results):
            raise RuntimeError(
                "replaced knowledge remains readable through normal search"
            )


def assimilation_decision_id(
    *,
    candidate_id: str,
    disposition: str,
    knowledge_ids: Sequence[str],
    predecessor_ids: Sequence[str] = (),
    reason: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "harness-mem:assimilation-decision:"
            f"{candidate_id}:{disposition}:{','.join(knowledge_ids)}:"
            f"{','.join(predecessor_ids)}:{reason}",
        )
    )


async def _current_entries_match(
    store: Any,
    *,
    project_name: str,
    expected_entries: Sequence[KnowledgeEntry],
) -> bool:
    if not expected_entries:
        return False
    for expected in expected_entries:
        current = await store.get_entry(expected.id, project_name=project_name)
        if current is None or (
            current.project_name != expected.project_name
            or current.module_path != expected.module_path
            or current.title != expected.title
            or current.statement != expected.statement
        ):
            return False
    return True


def _required_project_root(value: str | Path | None) -> Path:
    if value is None:
        raise ValueError("knowledge change requires an explicit project root")
    return Path(value).expanduser().resolve()


async def resolve_candidate_source_context(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    evidence_items: Sequence[KnowledgeEvidence],
    project_root: str | Path | None,
) -> tuple[Path, list[ProjectKnowledgeSourceRef], Any]:
    if len(evidence_items) != 1:
        raise ValueError("knowledge candidate requires one evidence envelope")
    evidence = evidence_items[0]
    job = (
        backend.transcript_store.get_distill_job(evidence.distill_job_id)
        if evidence.distill_job_id
        else None
    )
    revision = (
        backend.transcript_store.get_revision(job.source_id, job.source_revision)
        if job is not None
        else None
    )
    root_value = project_root or (job.project_root if job is not None else None)
    if root_value is None:
        profile = await LocalProjectProfileStore(backend.data_dir).get(
            candidate.project_name
        )
        root_value = profile.project_root if profile is not None else None
    root = _required_project_root(root_value)
    source_refs: list[ProjectKnowledgeSourceRef] = []
    for ref in evidence.verification_refs:
        if ref.kind == "repository" and ref.locator:
            path = (root / ref.locator).resolve()
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=ref.locator,
                    target=path.as_uri(),
                    kind="repository",
                    digest=ref.content_sha256,
                )
            )
            continue
        if ref.kind == "user_statement" and ref.exchange_index is not None:
            if job is None or revision is None:
                raise ValueError(
                    "user-statement knowledge requires its retained transcript revision"
                )
            source_target = Path(backend.transcript_store.db_path).resolve().as_uri()
            source_fragment = urlencode(
                {
                    "source_id": job.source_id,
                    "source_revision": job.source_revision,
                    "exchange": ref.exchange_index,
                }
            )
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=f"原始会话 Exchange {ref.exchange_index}",
                    target=f"{source_target}#{source_fragment}",
                    kind="user_statement",
                    digest=ref.content_sha256,
                )
            )
            continue
        if ref.kind == "transcript" and (
            ref.chunk_index is not None or ref.exchange_index is not None
        ):
            if job is None or revision is None:
                raise ValueError(
                    "transcript knowledge requires its retained transcript revision"
                )
            source_target = Path(backend.transcript_store.db_path).resolve().as_uri()
            location_name = "chunk" if ref.chunk_index is not None else "exchange"
            location_value = (
                ref.chunk_index if ref.chunk_index is not None else ref.exchange_index
            )
            source_fragment = urlencode(
                {
                    "source_id": job.source_id,
                    "source_revision": job.source_revision,
                    location_name: location_value,
                }
            )
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=f"原始会话 {location_name.title()} {location_value}",
                    target=f"{source_target}#{source_fragment}",
                    kind="transcript",
                    digest=ref.content_sha256,
                )
            )
    if not source_refs:
        raise ValueError("verified knowledge has no readable source reference")
    return root, source_refs, evidence.verified_at


async def resolve_separated_review(
    backend: LocalMemoryBackend,
    *,
    candidate_id: str,
    disposition: AssimilationDisposition,
    reason: str,
    knowledge_items: Sequence[Mapping[str, Any]] = (),
    target_knowledge_ids: Sequence[str] = (),
    project_root: str | Path | None = None,
    expected_project_name: str | None = None,
) -> dict[str, Any]:
    """Apply an explicit Review decision through the same separated ledger.

    Review may reject or defer any candidate.  It may write current knowledge
    only after the candidate already has verified evidence; this keeps a Dream
    discovery from bypassing the verification module.
    """

    store = backend.structured_store.knowledge_store
    candidate = await store.get_candidate(candidate_id)
    if candidate is None:
        raise ValueError("knowledge review candidate is missing")
    if expected_project_name and candidate.project_name != expected_project_name:
        raise ValueError("knowledge review candidate belongs to another project")
    if candidate.status in {"assimilated", "rejected"}:
        raise ValueError("knowledge review candidate already has a terminal decision")
    if candidate.status not in {"pending", "deferred", "conflict"}:
        raise ValueError("knowledge review candidate has an unsupported status")
    evidence_items = await store.list_evidence(candidate.id)

    items = [dict(item) for item in knowledge_items]
    writes_truth = disposition in {"add", "refine", "replace"}
    needs_verified_evidence = writes_truth or disposition == "confirm"
    resolved_root: Path | None = None
    source_refs: list[ProjectKnowledgeSourceRef] = []
    verified_at: Any = None
    if needs_verified_evidence:
        if len(evidence_items) != 1 or evidence_items[0].verification_outcome != "verified":
            raise ValueError(
                "knowledge review requires verified evidence before confirmation or truth write"
            )
        resolved_root, source_refs, _previous_verified_at = (
            await resolve_candidate_source_context(
                backend,
                candidate=candidate,
                evidence_items=evidence_items,
                project_root=project_root,
            )
        )
        evidence = evidence_items[0]
        subject = SimpleNamespace(
            id=candidate.id,
            project_name=candidate.project_name,
            distill_job_id=evidence.distill_job_id,
            evidence_basis=evidence.evidence_basis,
            verification_outcome=evidence.verification_outcome,
            verification_refs=list(evidence.verification_refs),
            verification_reason_codes=list(evidence.verification_reason_codes),
            verified_at=evidence.verified_at,
        )
        validation = await validate_candidate_evidence(
            backend,
            subject,
            project_root=resolved_root,
        )
        if validation.verification_outcome != "verified":
            reasons = ", ".join(validation.reason_codes) or "source unavailable"
            raise ValueError(
                "knowledge review requires current verified evidence: " + reasons
            )
        verified_at = validation.verified_at
    if writes_truth and not items:
        raise ValueError(
            "knowledge review truth write requires canonical knowledge items"
        )
    if disposition in {"refine", "replace"} and not target_knowledge_ids:
        raise ValueError(f"{disposition} requires at least one current knowledge target")
    if disposition == "confirm" and len(target_knowledge_ids) != 1:
        raise ValueError("confirm requires exactly one current knowledge target")

    # Resolve every existing-truth dependency before creating a replacement.
    # Otherwise an invalid target would leave an orphan current entry behind
    # even though no assimilation decision can validly own it.
    targets: list[KnowledgeEntry] = []
    if disposition in {"refine", "replace", "confirm"}:
        assert resolved_root is not None
        for target_id in target_knowledge_ids:
            target = await store.get_entry(
                str(target_id),
                project_name=candidate.project_name,
                project_root=resolved_root,
            )
            if target is None or target.project_name != candidate.project_name:
                raise ValueError("review target is not current project knowledge")
            targets.append(target)
        if disposition == "confirm":
            target_validation = await validate_knowledge_sources(
                backend,
                project_name=candidate.project_name,
                sources=await store.list_sources(targets[0].id),
                project_root=resolved_root,
            )
            if target_validation.verification_outcome != "verified":
                reasons = ", ".join(target_validation.reason_codes)
                raise ValueError(
                    "review target source is no longer current: " + reasons
                )

    if disposition in {"refine", "replace", "confirm"} and not targets:
        raise AssertionError("review target was not preflighted")
    point = {
        "disposition": disposition,
        "matched_truth_ids": list(target_knowledge_ids),
        "knowledge_items": items,
        "reason": reason,
        "verified_at": verified_at,
    }
    truth_ids = await record_assimilation_result(
        backend,
        candidate=candidate,
        point=point,
        project_root=resolved_root,
        source_refs=source_refs,
    )
    return {
        "candidate_id": candidate.id,
        "disposition": disposition,
        "canonical_truth_ids": truth_ids,
        "changed": bool(writes_truth),
    }


async def delete_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_knowledge_ids: Sequence[str],
) -> dict[str, Any]:
    """Delete exactly one current project-knowledge entry."""

    normalized_project = str(project_name).strip()
    targets = [str(value).strip() for value in target_knowledge_ids]
    if not normalized_project:
        raise ValueError("knowledge delete requires project_name")
    if len(targets) != 1 or not targets[0]:
        raise ValueError("knowledge delete requires exactly one target knowledge id")

    entry_id = targets[0]
    store = backend.structured_store.knowledge_store
    current = await store.get_entry(
        entry_id,
        project_name=normalized_project,
    )
    if current is None:
        raise ValueError("knowledge delete target is not current project knowledge")
    await store.delete_current_entry(
        project_name=normalized_project,
        entry_id=entry_id,
    )
    await _verify_normal_search_after_truth_write(
        backend,
        project_name=normalized_project,
        project_root=None,
        added_entries=[],
        predecessor_entries=[current],
    )
    if await store.list_sources(entry_id):
        raise RuntimeError("deleted knowledge sources remain in current storage")
    return {
        "deleted_knowledge_ids": [entry_id],
    }


def _knowledge_items(point: Mapping[str, Any]) -> list[dict[str, Any]]:
    supplied = list(point.get("knowledge_items") or [])
    if supplied:
        normalized: list[dict[str, Any]] = []
        for item in supplied:
            title = str(item.get("title") or "").strip()
            statement = str(item.get("statement") or "").strip()
            topic_path = [str(part).strip() for part in item.get("topic_path") or []]
            claim_kind = str(item.get("claim_kind") or "")
            if not title or not statement or not topic_path:
                raise ValueError(
                    "review knowledge item must have title, statement, and topic path"
                )
            if claim_kind not in {
                "design_requirement",
                "implementation_fact",
                "durable_preference",
                "procedure",
            }:
                raise ValueError("review knowledge item has an invalid claim kind")
            normalized.append(
                {
                    "title": title,
                    "statement": statement,
                    "topic_path": topic_path,
                    "claim_kind": claim_kind,
                }
            )
        return normalized

    title = str(point.get("canonical_title") or "").strip()
    statement = str(point.get("canonical_statement") or "").strip()
    topic_path = [str(part).strip() for part in point.get("topic_path") or []]
    if not title or not statement or not topic_path:
        raise ValueError("a knowledge-writing disposition requires an atomic item")
    return [
        {
            "title": title,
            "statement": statement,
            "topic_path": topic_path,
            "claim_kind": str(point.get("claim_kind") or "procedure"),
        }
    ]


def _separated_status(disposition: AssimilationDisposition) -> KnowledgeCandidateStatus:
    if disposition == "defer":
        return "deferred"
    if disposition == "conflict":
        return "conflict"
    if disposition == "reject":
        return "rejected"
    return "assimilated"


def _disposition(point: Mapping[str, Any]) -> AssimilationDisposition:
    value = str(point.get("disposition") or "reject")
    allowed = {
        "add",
        "refine",
        "confirm",
        "replace",
        "no_write",
        "handoff",
        "defer",
        "conflict",
        "reject",
    }
    if value not in allowed:
        raise ValueError(f"unknown assimilation disposition: {value}")
    return cast(AssimilationDisposition, value)


__all__ = [
    "delete_current_knowledge",
    "record_assimilation_result",
    "resolve_candidate_source_context",
    "resolve_separated_review",
]
