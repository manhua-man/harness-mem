"""Autonomous candidate admission and assimilation without legacy writes.

This is the new-session side of the knowledge-truth separation boundary.  It
uses the existing evidence gate, but represents its input as a short-lived
admission subject rather than persisting a ``MemoryEntry`` / ``RuleCandidate``
/ ``RelationFact`` first.  The durable rows are therefore limited to the four
separated knowledge collections (plus an explicit task handoff when needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from uuid import NAMESPACE_URL, uuid5

from harness_mem.commands.evidence_admission import (
    answer_gate_status,
    apply_validation,
    validate_candidate_evidence,
)
from harness_mem.commands.knowledge_assimilation import (
    record_assimilation_result,
    resolve_candidate_source_context,
)
from harness_mem.core.schemas import (
    EvidenceRef,
    KnowledgeCandidate,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_MAX_CURRENT_TRUTH = 12


@dataclass(frozen=True)
class SeparatedPreparedAssimilation:
    """Verified separated candidates plus a transcript-free provider manifest."""

    project_name: str
    project_root: str
    candidate_ids: tuple[str, ...]
    eligible_candidate_ids: tuple[str, ...]
    automatic_points: tuple[dict[str, Any], ...]
    answer_status_by_candidate: dict[str, str]
    truth_by_handle: dict[str, str]
    manifest: dict[str, Any]


@dataclass
class _EvidenceAdmissionSubject:
    """The minimal in-memory shape consumed by the trusted evidence gate."""

    id: str
    project_name: str
    distill_job_id: str | None
    evidence_basis: str | None
    verification_outcome: str | None
    verification_refs: list[EvidenceRef]
    verification_reason_codes: list[str]
    verified_at: datetime | None = None


async def create_separated_candidates(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str,
    candidate_arguments: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Persist validated extraction points directly in the separated tables.

    ``candidate_arguments`` is already kind-validated and evidence-sanitized by
    the worker.  The trusted runtime nevertheless revalidates each reference
    before the candidate becomes eligible for assimilation.
    """

    store = backend.structured_store.knowledge_store
    # A failed semantic attempt can have already admitted candidate/evidence
    # rows even though the job never finalized.  A retry receives a fresh,
    # independently shaped extraction decision, so those pending rows must
    # become audited deferred history before the new attempt is created.
    # Otherwise they remain job-bound and make the later finalization reject a
    # valid new plan as an incomplete candidate set.
    for existing in await store.list_candidates(project_name):
        if existing.status != "pending":
            continue
        if any(
            evidence.distill_job_id == distill_job_id
            for evidence in await store.list_evidence(existing.id)
        ):
            await record_assimilation_result(
                backend,
                candidate=existing,
                point={
                    "disposition": "defer",
                    "reason": (
                        "Replaced by a fresh extraction attempt before the "
                        "distill job finalized."
                    ),
                },
            )
    candidate_ids: list[str] = []
    for index, arguments in enumerate(candidate_arguments, 1):
        kind = str(arguments.get("kind") or "")
        if kind not in {"memory", "rule", "relation"}:
            raise ValueError("separated candidate kind must be memory, rule, or relation")
        statement = _statement(arguments, kind=kind)
        candidate_id = str(
            uuid5(
                NAMESPACE_URL,
                f"harness-mem:autonomous-knowledge-candidate:{distill_job_id}:"
                f"{index}:{kind}:{statement}",
            )
        )
        candidate = KnowledgeCandidate(
            id=candidate_id,
            project_name=project_name,
            candidate_type=cast(Any, kind),
            statement=statement,
        )
        refs = _evidence_refs(arguments.get("verification_refs") or [])
        subject = _EvidenceAdmissionSubject(
            id=candidate_id,
            project_name=project_name,
            distill_job_id=distill_job_id,
            evidence_basis=_required_evidence_basis(arguments),
            verification_outcome=_requested_verification_outcome(arguments),
            verification_refs=refs,
            verification_reason_codes=[
                str(value)
                for value in arguments.get("verification_reason_codes") or []
            ],
        )
        validation = await validate_candidate_evidence(backend, subject)
        apply_validation(subject, validation)
        await store.save_candidate(candidate)
        evidence = KnowledgeEvidence(
            id=_evidence_id(candidate_id),
            project_name=project_name,
            candidate_id=candidate_id,
            distill_job_id=distill_job_id,
            evidence_basis=cast(Any, subject.evidence_basis or "transcript"),
            verification_outcome=cast(
                Any, subject.verification_outcome or "unverified"
            ),
            verification_refs=subject.verification_refs,
            verification_reason_codes=list(subject.verification_reason_codes),
            verified_at=subject.verified_at,
        )
        await store.save_evidence(evidence)
        candidate_ids.append(candidate_id)
    return candidate_ids


async def prepare_separated_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    candidate_ids: Sequence[str],
) -> SeparatedPreparedAssimilation:
    """Revalidate direct candidates and prepare the bounded semantic manifest."""

    store = backend.structured_store.knowledge_store
    candidates: list[KnowledgeCandidate] = []
    evidence_by_candidate: dict[str, KnowledgeEvidence] = {}
    answer_statuses: dict[str, str] = {}
    for candidate_id in candidate_ids:
        candidate = await store.get_candidate(str(candidate_id))
        if candidate is None:
            raise ValueError(f"separated candidate is missing: {candidate_id}")
        if candidate.project_name != project_name:
            raise ValueError("separated candidate belongs to another project")
        evidence = _job_bound_evidence(
            await store.list_evidence(candidate.id), candidate_id=candidate.id
        )
        subject = _subject(candidate, evidence)
        validation = await validate_candidate_evidence(backend, subject)
        apply_validation(subject, validation)
        evidence.evidence_basis = cast(Any, subject.evidence_basis or "transcript")
        evidence.verification_outcome = cast(
            Any, subject.verification_outcome or "unverified"
        )
        evidence.verification_reason_codes = list(subject.verification_reason_codes)
        evidence.verified_at = subject.verified_at
        await store.save_evidence(evidence)
        candidates.append(candidate)
        evidence_by_candidate[candidate.id] = evidence
        answer_statuses[candidate.id] = answer_gate_status(subject)

    automatic: list[dict[str, Any]] = []
    eligible: list[KnowledgeCandidate] = []
    for candidate in candidates:
        status = answer_statuses[candidate.id]
        evidence = evidence_by_candidate[candidate.id]
        if _is_non_durable_verified_point(evidence):
            automatic.append(
                _automatic_point(
                    candidate.id,
                    answer_status=status,
                    disposition="no_write",
                    reason=(
                        "A clarification of this session's review scope is not "
                        "current project knowledge."
                    ),
                )
            )
        elif status == "ANSWERED":
            eligible.append(candidate)
        else:
            automatic.append(_automatic_point(candidate.id, answer_status=status))

    truth_by_handle, current_truth = await _current_truth_handles(
        backend,
        project_name=project_name,
        project_root=project_root,
        candidates=eligible,
    )
    return SeparatedPreparedAssimilation(
        project_name=project_name,
        project_root=project_root,
        candidate_ids=tuple(item.id for item in candidates),
        eligible_candidate_ids=tuple(item.id for item in eligible),
        automatic_points=tuple(automatic),
        answer_status_by_candidate=answer_statuses,
        truth_by_handle=truth_by_handle,
        manifest={
            "contract_version": "separated-knowledge-assimilation-v1",
            "project_name": project_name,
            "current_modules": sorted(
                {
                    item["topic_path"][0]
                    for item in current_truth
                    if item.get("topic_path")
                }
            ),
            "verified_candidates": [
                _candidate_projection(candidate, evidence_by_candidate[candidate.id])
                for candidate in eligible
            ],
            "current_truth": current_truth,
        },
    )


def validate_separated_assimilation_decision(
    prepared: SeparatedPreparedAssimilation,
    decision: Any,
) -> dict[str, Any]:
    """Validate complete per-point coverage without accepting legacy targets."""

    points = list(decision.points)
    ids = [str(point.candidate_id) for point in points]
    expected = set(prepared.eligible_candidate_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("assimilation decision contains duplicate candidate ids")
    if set(ids) != expected:
        raise ValueError("assimilation decision must cover every verified candidate once")

    normalized: list[dict[str, Any]] = [dict(item) for item in prepared.automatic_points]
    for point in points:
        handles = [str(handle) for handle in point.matched_truth_handles]
        if len(handles) != len(set(handles)):
            raise ValueError("assimilation point contains duplicate truth handles")
        if any(handle not in prepared.truth_by_handle for handle in handles):
            raise ValueError("assimilation point references an unavailable truth handle")
        disposition = str(point.disposition)
        if disposition == "add" and handles:
            raise ValueError("add must not target current truth")
        if disposition in {"confirm", "refine", "supersede"} and len(handles) != 1:
            raise ValueError(f"{disposition} requires exactly one current truth handle")
        if disposition == "conflict" and len(handles) > 1:
            raise ValueError("conflict may reference at most one current truth handle")
        knowledge_items = [item.model_dump() for item in point.knowledge_items]
        if disposition in {"add", "refine", "supersede"}:
            if knowledge_items:
                if point.canonical_title or point.canonical_statement:
                    raise ValueError(
                        "knowledge_items and legacy canonical fields cannot both write truth"
                    )
                if disposition == "refine" and len(knowledge_items) != 1:
                    raise ValueError(
                        "refine requires exactly one replacement knowledge item"
                    )
            elif (
                not str(point.canonical_title or "").strip()
                or not str(point.canonical_statement or "").strip()
            ):
                raise ValueError(f"{disposition} requires canonical knowledge")
        normalized.append(
            {
                "candidate_id": str(point.candidate_id),
                "answer_status": "ANSWERED",
                "disposition": disposition,
                "matched_truth_ids": [prepared.truth_by_handle[handle] for handle in handles],
                "matched_truth_kinds": ["knowledge_entry" for _handle in handles],
                "canonical_title": point.canonical_title,
                "canonical_statement": point.canonical_statement,
                "topic_path": list(point.topic_path),
                "knowledge_items": knowledge_items,
                "reason": point.reason,
            }
        )
    normalized.sort(key=lambda item: prepared.candidate_ids.index(item["candidate_id"]))
    return {
        "version": "separated-v1",
        "candidate_ids": list(prepared.candidate_ids),
        "point_count": len(normalized),
        "points": normalized,
        "provider_candidate_ids": list(prepared.eligible_candidate_ids),
    }


async def apply_separated_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    candidate_ids: Sequence[str],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a validated separated plan; legacy truth is never mutated here."""

    expected = [str(value) for value in candidate_ids]
    points = list(plan.get("points") or [])
    actual = [str(item.get("candidate_id") or "") for item in points]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError("separated assimilation plan does not cover this job's candidates")
    if len(actual) != len(set(actual)):
        raise ValueError("separated assimilation plan has duplicate candidate results")

    store = backend.structured_store.knowledge_store
    results: list[dict[str, Any]] = []
    counts = {
        "suggested": len(expected),
        "promoted": 0,
        "confirmed": 0,
        "no_write": 0,
        "handoff": 0,
        "deferred": 0,
        "conflict": 0,
        "rejected": 0,
        "missing": 0,
        "pending": 0,
    }
    for point in points:
        candidate_id = str(point["candidate_id"])
        candidate = await store.get_candidate(candidate_id)
        if candidate is None:
            counts["missing"] += 1
            continue
        if candidate.project_name != project_name:
            raise ValueError("separated assimilation candidate belongs to another project")
        evidence = _job_bound_evidence(
            await store.list_evidence(candidate.id), candidate_id=candidate.id
        )
        subject = _subject(candidate, evidence)
        status = answer_gate_status(subject)
        disposition = str(point.get("disposition") or "reject")
        record_point = dict(point)
        if not record_point.get("knowledge_items"):
            record_point["claim_kind"] = _fallback_claim_kind(candidate, evidence)
        source_refs: list[ProjectKnowledgeSourceRef] = []
        resolved_root = Path(project_root).expanduser().resolve()
        if disposition in {"add", "refine", "supersede", "confirm"}:
            resolved_root, source_refs, verified_at = await resolve_candidate_source_context(
                backend,
                candidate=candidate,
                evidence_items=[evidence],
                project_root=project_root,
            )
            record_point["verified_at"] = verified_at
        truth_ids = await record_assimilation_result(
            backend,
            candidate=candidate,
            point=record_point,
            project_root=resolved_root,
            source_refs=source_refs,
        )
        handoff_id: str | None = None
        if disposition == "handoff":
            handoff_id = await _materialize_handoff(
                backend, candidate=candidate, evidence=evidence, point=point
            )
        result = {
            "candidate_id": candidate.id,
            "answer_status": status,
            "disposition": disposition,
            "canonical_truth_ids": truth_ids,
            "separated_knowledge_ids": truth_ids,
            "handoff_id": handoff_id,
        }
        results.append(result)
        if disposition in {"add", "refine", "supersede"}:
            counts["promoted"] += 1
        elif disposition == "confirm":
            counts["confirmed"] += 1
        elif disposition == "no_write":
            counts["no_write"] += 1
        elif disposition == "handoff":
            counts["handoff"] += 1
        elif disposition == "defer":
            counts["deferred"] += 1
        elif disposition == "conflict":
            counts["conflict"] += 1
        else:
            counts["rejected"] += 1
    return {**counts, "points": results}


async def separated_job_candidate_ids(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str,
) -> list[str]:
    """Return only direct candidates whose evidence binds them to this job."""

    store = backend.structured_store.knowledge_store
    matches: list[str] = []
    for candidate in await store.list_candidates(project_name):
        if candidate.status != "pending":
            continue
        if any(
            evidence.distill_job_id == distill_job_id
            for evidence in await store.list_evidence(candidate.id)
        ):
            matches.append(candidate.id)
    return sorted(matches)


def _statement(arguments: Mapping[str, Any], *, kind: str) -> str:
    if kind == "memory":
        statement = str(arguments.get("content") or "").strip()
    elif kind == "rule":
        statement = "When {trigger}, {pattern}".format(
            trigger=str(arguments.get("trigger") or "").strip(),
            pattern=str(arguments.get("pattern") or "").strip(),
        ).strip()
    else:
        statement = "{source} {relation} {target}".format(
            source=str(arguments.get("source_entity") or "").strip(),
            relation=str(arguments.get("relation_type") or "").strip(),
            target=str(arguments.get("target_entity") or "").strip(),
        ).strip()
    if not statement:
        raise ValueError("separated candidate statement is empty")
    return statement


def _evidence_refs(values: Sequence[Any]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for value in values:
        if isinstance(value, EvidenceRef):
            refs.append(value)
        elif isinstance(value, Mapping):
            refs.append(EvidenceRef.model_validate(dict(value)))
        else:
            raise ValueError("candidate verification ref is invalid")
    return refs


def _required_evidence_basis(arguments: Mapping[str, Any]) -> str:
    value = str(arguments.get("evidence_basis") or "")
    if value not in {"repository", "user_statement", "transcript"}:
        raise ValueError("candidate evidence basis is invalid")
    return value


def _requested_verification_outcome(arguments: Mapping[str, Any]) -> str:
    value = str(arguments.get("verification_outcome") or "")
    if value not in {"verified", "unverified", "contradicted", "not_applicable"}:
        raise ValueError("candidate verification outcome is invalid")
    return value


def _evidence_id(candidate_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge-evidence:{candidate_id}"))


def _job_bound_evidence(
    evidence_items: Sequence[KnowledgeEvidence], *, candidate_id: str
) -> KnowledgeEvidence:
    if len(evidence_items) != 1:
        raise ValueError(
            f"separated candidate requires exactly one evidence envelope: {candidate_id}"
        )
    return evidence_items[0]


def _subject(
    candidate: KnowledgeCandidate, evidence: KnowledgeEvidence
) -> _EvidenceAdmissionSubject:
    return _EvidenceAdmissionSubject(
        id=candidate.id,
        project_name=candidate.project_name,
        distill_job_id=evidence.distill_job_id,
        evidence_basis=evidence.evidence_basis,
        verification_outcome=evidence.verification_outcome,
        verification_refs=list(evidence.verification_refs),
        verification_reason_codes=list(evidence.verification_reason_codes),
        verified_at=evidence.verified_at,
    )


def _automatic_point(
    candidate_id: str,
    *,
    answer_status: str,
    disposition: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if disposition is None:
        if answer_status in {"CONTRADICTED", "STALE"}:
            disposition = "reject"
        elif answer_status == "NOT_APPLICABLE":
            disposition = "no_write"
        else:
            disposition = "defer"
    return {
        "candidate_id": candidate_id,
        "answer_status": answer_status,
        "disposition": disposition,
        "matched_truth_ids": [],
        "matched_truth_kinds": [],
        "canonical_title": None,
        "canonical_statement": None,
        "topic_path": [],
        "knowledge_items": [],
        "reason": reason or f"runtime evidence gate is {answer_status}",
    }


def _is_non_durable_verified_point(evidence: KnowledgeEvidence) -> bool:
    """Keep a one-off review boundary out of the durable knowledge layer.

    The trusted evidence gate distinguishes an explicit clarification of the
    *current* review's scope from a user-authored project workflow or design
    requirement.  The former is useful in the session Note, but treating its
    component list as several future rules creates exactly the retrieval noise
    the separated assimilation layer exists to prevent.
    """

    return bool(
        {
            "explicit_scope_clarification",
            "session_only_not_durable",
        }.intersection(evidence.verification_reason_codes)
    )


def _is_session_scope_clarification(evidence: KnowledgeEvidence) -> bool:
    """Compatibility alias for the original focused contract test."""

    return _is_non_durable_verified_point(evidence)


def _candidate_projection(
    candidate: KnowledgeCandidate, evidence: KnowledgeEvidence
) -> dict[str, Any]:
    subject = _subject(candidate, evidence)
    return {
        "candidate_id": candidate.id,
        "kind": candidate.candidate_type,
        "statement": candidate.statement,
        "evidence_basis": evidence.evidence_basis,
        "verification_reason_codes": list(evidence.verification_reason_codes),
        "answer_status": answer_gate_status(subject),
    }


async def _current_truth_handles(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    candidates: Sequence[KnowledgeCandidate],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Expose only current separated truth; legacy rows remain read-only history."""

    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name,
        project_root=project_root,
    )
    terms = {
        token.casefold()
        for candidate in candidates
        for token in candidate.statement.split()
        if len(token) >= 4
    }
    entries.sort(
        key=lambda entry: (
            -sum(
                token.casefold().strip(".,:;()") in terms
                for token in entry.statement.split()
            ),
            entry.id,
        )
    )
    handles: dict[str, str] = {}
    projected: list[dict[str, Any]] = []
    for index, entry in enumerate(entries[:_MAX_CURRENT_TRUTH], 1):
        handle = f"T{index}"
        handles[handle] = entry.id
        projected.append(
            {
                "handle": handle,
                "kind": "knowledge_entry",
                "title": entry.title,
                "statement": entry.statement,
                "topic_path": list(entry.module_path),
            }
        )
    return handles, projected


async def _materialize_handoff(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    evidence: KnowledgeEvidence,
    point: Mapping[str, Any],
) -> str:
    handoff_id = str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge-handoff:{candidate.id}"))
    existing = await backend.structured_store.get_task_handoff(handoff_id)
    if existing is not None:
        return existing.id
    statement = str(point.get("canonical_statement") or candidate.statement)
    handoff = TaskHandoff(
        id=handoff_id,
        project_name=candidate.project_name,
        task_id=f"assimilation:{candidate.id}",
        summary=statement,
        status="in_progress",
        next_steps=[statement],
        context={
            "distill_job_id": evidence.distill_job_id,
            "candidate_id": candidate.id,
        },
    )
    return await backend.structured_store.save_task_handoff(handoff)


def _fallback_claim_kind(
    candidate: KnowledgeCandidate, evidence: KnowledgeEvidence
) -> str:
    """Use conservative language when old canonical fields omit claim kind.

    New providers normally return ``knowledge_items`` with an explicit claim
    kind.  The fallback keeps a user-stated preference from pretending to be a
    verified implementation fact while preserving existing deterministic
    fixtures during the transition.
    """

    if candidate.candidate_type == "rule":
        return "procedure"
    if (
        evidence.evidence_basis == "repository"
        and evidence.verification_outcome == "verified"
    ):
        return "implementation_fact"
    if (
        evidence.evidence_basis == "user_statement"
        and evidence.verification_outcome == "verified"
    ):
        return "durable_preference"
    return "procedure"


__all__ = [
    "SeparatedPreparedAssimilation",
    "apply_separated_assimilation",
    "create_separated_candidates",
    "prepare_separated_assimilation",
    "separated_job_candidate_ids",
    "validate_separated_assimilation_decision",
]
