"""Autonomous candidate admission and assimilation without legacy writes.

This is the new-session side of the knowledge-truth separation boundary.  It
uses the existing evidence gate, but represents its input as a short-lived
admission subject rather than persisting a ``MemoryEntry`` / ``RuleCandidate``
/ ``RelationFact`` first.  The durable rows are therefore limited to the four
    current knowledge and its source locators (plus a task handoff when needed).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
from typing import Any, Literal, Mapping, Sequence, cast
from uuid import NAMESPACE_URL, uuid5

from harness_mem.commands.evidence_admission import (
    answer_gate_status,
    apply_validation,
    validate_candidate_evidence,
)
from harness_mem.commands.knowledge_assimilation import (
    record_assimilation_result,
    is_committed_knowledge_point,
    resolve_candidate_source_context,
    normalize_knowledge_targets,
    KnowledgeTargetError,
    resolve_knowledge_targets,
)
from harness_mem.core.schemas import (
    EvidenceRef,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


_ASSIMILATION_DISPOSITIONS = {
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
_WRITING_DISPOSITIONS = {"add", "refine", "replace"}
FORBIDDEN_KNOWLEDGE_MODULE_NAMES: frozenset[str] = frozenset()


def validate_knowledge_module_path(path: Sequence[str]) -> list[str]:
    """Validate structure without a hard-coded module vocabulary."""

    normalized = [str(part).strip() for part in path if str(part).strip()]
    if not normalized:
        raise ValueError("topic_path must name a natural project module")
    return normalized


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
    statement: str = ""
    source_report: SourceReport | None = None


async def admit_separated_candidate(
    backend: LocalMemoryBackend,
    *,
    candidate_id: str,
    project_name: str,
    candidate_type: str,
    statement: str,
    distill_job_id: str | None,
    evidence_basis: str,
    verification_outcome: str,
    verification_refs: Sequence[Any] = (),
    verification_reason_codes: Sequence[str] = (),
    assimilation_disposition: str | None = None,
    assimilation_reason: str | None = None,
    assimilation_target_ids: Sequence[str] = (),
    assimilation_targets: Sequence[Mapping[str, Any]] = (),
    canonical_title: str | None = None,
    topic_path: Sequence[str] = (),
) -> tuple[KnowledgeCandidate, bool]:
    """Admit one proposal directly into the finite-lifetime knowledge workspace."""

    kind = str(candidate_type).strip()
    if kind not in {"memory", "rule", "relation"}:
        raise ValueError("separated candidate kind must be memory, rule, or relation")
    normalized_statement = " ".join(str(statement).split())
    if not normalized_statement:
        raise ValueError("separated candidate statement is empty")

    store = backend.structured_store.knowledge_store
    candidate = await store.get_candidate(candidate_id)
    replay = candidate is not None
    if candidate is None:
        candidate = KnowledgeCandidate(
            id=candidate_id,
            project_name=project_name,
            candidate_type=cast(Any, kind),
            statement=normalized_statement,
        )
    elif (
        candidate.project_name != project_name
        or candidate.candidate_type != kind
        or candidate.statement != normalized_statement
    ):
        raise ValueError("separated candidate id already belongs to another proposal")
    elif candidate.status != "pending":
        raise ValueError("separated candidate already has a processing result")

    refs = _evidence_refs(verification_refs)
    if replay:
        previous_evidence = await store.list_evidence(candidate.id)
        report_authority = candidate.source_report is not None or any(
            item.evidence_basis == "source_report" for item in previous_evidence
        )
        if report_authority or evidence_basis == "source_report":
            if (len(previous_evidence) != 1
                    or previous_evidence[0].evidence_basis != evidence_basis
                    or previous_evidence[0].distill_job_id != distill_job_id):
                raise ValueError("source-report replay cannot change its bound authority or source job")
            if candidate.source_report is not None:
                def identity(ref: EvidenceRef) -> tuple:
                    return (ref.kind, ref.role, ref.exchange_index, ref.chunk_index,
                            str(ref.content_sha256 or "").lower(), ref.locator,
                            str(ref.locator_sha256 or "").lower())
                if {identity(ref) for ref in refs} != {
                    identity(ref) for ref in previous_evidence[0].verification_refs
                }:
                    raise ValueError("source-report replay cannot change its speaker or cited scope")

    candidate.assimilation_disposition = cast(Any, assimilation_disposition)
    candidate.assimilation_reason = assimilation_reason
    candidate.assimilation_target_ids = [
        str(value).strip() for value in assimilation_target_ids if str(value).strip()
    ]
    candidate.assimilation_targets = normalize_knowledge_targets(assimilation_targets)
    candidate.canonical_title = canonical_title
    candidate.topic_path = [str(part).strip() for part in topic_path if str(part).strip()]
    candidate.updated_at = datetime.now(timezone.utc)

    subject = _EvidenceAdmissionSubject(
        id=candidate.id,
        project_name=project_name,
        distill_job_id=distill_job_id,
        evidence_basis=evidence_basis,
        verification_outcome=verification_outcome,
        verification_refs=refs,
        verification_reason_codes=[str(value) for value in verification_reason_codes],
        statement=candidate.statement,
        source_report=candidate.source_report,
    )
    project_root: str | None = None
    if evidence_basis == "repository" and distill_job_id is None:
        profile = await LocalProjectProfileStore(backend.data_dir).get(project_name)
        project_root = profile.project_root if profile is not None else None
    validation = await validate_candidate_evidence(
        backend,
        subject,
        project_root=project_root,
    )
    apply_validation(subject, validation)
    if subject.source_report is not None:
        candidate.source_report = subject.source_report
    await store.save_candidate(candidate)
    await store.save_evidence(
        KnowledgeEvidence(
            id=_evidence_id(candidate.id),
            project_name=project_name,
            candidate_id=candidate.id,
            distill_job_id=distill_job_id,
            evidence_basis=cast(Any, subject.evidence_basis or "transcript"),
            verification_outcome=cast(
                Any, subject.verification_outcome or "unverified"
            ),
            verification_refs=subject.verification_refs,
            verification_reason_codes=list(subject.verification_reason_codes),
            verified_at=subject.verified_at,
        )
    )
    return candidate, replay


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
        replayed_candidate = await store.get_candidate(candidate_id)
        if replayed_candidate is not None and replayed_candidate.status != "pending":
            if (
                replayed_candidate.project_name != project_name
                or replayed_candidate.candidate_type != kind
                or replayed_candidate.statement != " ".join(statement.split())
            ):
                raise ValueError(
                    "separated candidate id already belongs to another proposal"
                )
            evidence = _job_bound_evidence(
                await store.list_evidence(replayed_candidate.id),
                candidate_id=replayed_candidate.id,
            )
            if evidence.distill_job_id != distill_job_id:
                raise ValueError("separated candidate replay belongs to another job")
            candidate_ids.append(candidate_id)
            continue
        await admit_separated_candidate(
            backend,
            candidate_id=candidate_id,
            project_name=project_name,
            candidate_type=kind,
            statement=statement,
            distill_job_id=distill_job_id,
            evidence_basis=_required_evidence_basis(arguments),
            verification_outcome=_requested_verification_outcome(arguments),
            verification_refs=arguments.get("verification_refs") or [],
            verification_reason_codes=arguments.get("verification_reason_codes") or [],
        )
        candidate_ids.append(candidate_id)
    return candidate_ids


def _non_promoting_transcript_disposition(
    candidate: KnowledgeCandidate,
) -> Literal["no_write", "reject"] | None:
    """Only a complete explicit discard may waive durable-truth promotion."""
    disposition = candidate.assimilation_disposition
    reason = str(candidate.assimilation_reason or "").strip()
    if (disposition in {"no_write", "reject"}
            and 8 <= len(reason) <= 1000
            and not candidate.assimilation_target_ids
            and not candidate.assimilation_targets
            and candidate.status != "conflict"):
        return cast(Literal["no_write", "reject"], disposition)
    return None


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
        validation = await validate_candidate_evidence(
            backend,
            subject,
            project_root=project_root,
            non_promoting_disposition=_non_promoting_transcript_disposition(candidate),
        )
        apply_validation(subject, validation)
        if subject.source_report is not None:
            candidate.source_report = subject.source_report
        await store.save_candidate(candidate)
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
        non_promoting = _non_promoting_transcript_disposition(candidate)
        if (status == "NOT_APPLICABLE" and evidence.evidence_basis == "transcript"
                and non_promoting is not None):
            automatic.append(_automatic_point(
                candidate.id, answer_status=status, disposition=non_promoting,
                reason=str(candidate.assimilation_reason).strip(),
            ))
        elif status == "ANSWERED" and _is_non_durable_verified_point(evidence):
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


def _validate_report_authority(
    prepared: SeparatedPreparedAssimilation, *, candidate_id: str,
    disposition: str, target_ids: Sequence[str],
) -> SourceReport | None:
    """Shared provider/apply preflight; never trust a serialized Answer Gate."""
    candidate_projection: dict[str, Any] = next((
        item for item in prepared.manifest.get("verified_candidates", [])
        if item["candidate_id"] == candidate_id
    ), {})
    payload = candidate_projection.get("source_report")
    report = SourceReport.model_validate({**payload, "text": candidate_projection["statement"]}) if payload else None
    current_by_id = {
        prepared.truth_by_handle.get(item["handle"]): item
        for item in prepared.manifest.get("current_truth", [])
    }
    for target_id in target_ids:
        current = current_by_id.get(target_id, {})
        target_report = current.get("source_report")
        if (report is None) != (target_report is None):
            raise ValueError("source-report and fact authority boundary cannot be crossed")
        if report is not None:
            target_account = SourceReport.model_validate({**target_report, "text": current["statement"]})
            if not report.same_account_source(target_account):
                raise ValueError("source-report updates cannot cross source, speaker, or period")
            if disposition == "confirm" and current.get("statement") != report.render_statement():
                raise ValueError("source-report confirmation requires the identical attributed account")
    return report


def _bind_report_items(
    report: SourceReport | None, items: list[dict[str, Any]], *, writes: bool,
) -> None:
    if report is not None and writes:
        if len(items) != 1:
            raise ValueError("source-report writes require exactly one verified account item")
        items[0].update(title=report.render_title(), statement=report.render_statement(), claim_kind="source_report")
    elif report is None and any(item["claim_kind"] == "source_report" for item in items):
        raise ValueError("source-report knowledge requires a verified attribution envelope")


def validate_separated_assimilation_decision(
    prepared: SeparatedPreparedAssimilation,
    decision: Any,
) -> dict[str, Any]:
    """Validate complete per-point coverage without accepting legacy targets."""

    decision = normalize_identical_replacements(prepared, decision)
    points = list(decision.points)
    ids = [str(point.candidate_id) for point in points]
    expected = set(prepared.eligible_candidate_ids)
    if set(ids) != expected:
        missing = sorted(expected - set(ids))
        extra = sorted(set(ids) - expected)
        if missing and extra:
            raise ValueError(
                "assimilation decision covers the wrong candidate set: missing "
                f"{missing}, extra {extra}"
            )
        if missing:
            raise ValueError(
                "assimilation decision must cover every verified candidate"
            )
        raise ValueError("assimilation decision contains unsupported candidate ids")

    normalized: list[dict[str, Any]] = [dict(item) for item in prepared.automatic_points]
    candidate_written_statements: dict[str, list[str]] = {}
    target_uses: dict[str, list[str]] = {}
    for point in points:
        handles = [str(handle) for handle in point.matched_truth_handles]
        if len(handles) != len(set(handles)):
            raise ValueError("assimilation point contains duplicate truth handles")
        if any(handle not in prepared.truth_by_handle for handle in handles):
            raise ValueError("assimilation point references an unavailable truth handle")
        disposition = str(point.disposition)
        report = _validate_report_authority(
            prepared, candidate_id=str(point.candidate_id), disposition=disposition,
            target_ids=[prepared.truth_by_handle[handle] for handle in handles],
        )
        for handle in handles:
            target_uses.setdefault(handle, []).append(disposition)
        if disposition == "add" and handles:
            raise ValueError("add must not target current truth")
        if disposition == "confirm" and len(handles) != 1:
            raise ValueError("confirm requires exactly one current truth handle")
        if disposition in {"refine", "replace"} and not handles:
            raise ValueError(f"{disposition} requires at least one current truth handle")
        if disposition == "conflict" and len(handles) > 1:
            raise ValueError("conflict may reference at most one current truth handle")
        if disposition in {"no_write", "handoff", "defer", "reject"} and handles:
            raise ValueError(f"{disposition} must not target current truth")
        knowledge_items = [item.model_dump() for item in point.knowledge_items]
        if disposition in {"add", "refine", "replace"}:
            if knowledge_items:
                if (
                    point.canonical_title
                    or point.canonical_statement
                    or point.topic_path
                ):
                    raise ValueError(
                        "knowledge_items and legacy canonical fields cannot both write truth"
                    )
                knowledge_items = [
                    _validate_canonical_knowledge_item(item)
                    for item in knowledge_items
                ]
                for item in knowledge_items:
                    item["topic_path"] = validate_knowledge_module_path(
                        item.get("topic_path") or []
                    )
                knowledge_items = _normalize_split_knowledge_items(knowledge_items)
            elif (
                not str(point.canonical_title or "").strip()
                or not str(point.canonical_statement or "").strip()
            ):
                raise ValueError(f"{disposition} requires canonical knowledge")
            else:
                point.topic_path = validate_knowledge_module_path(point.topic_path)
            _bind_report_items(report, knowledge_items, writes=True)
            candidate_written_statements.setdefault(str(point.candidate_id), []).extend(
                [str(item["statement"]) for item in knowledge_items]
                if knowledge_items
                else [str(point.canonical_statement or "")]
            )
        elif (
            knowledge_items
            or str(point.canonical_title or "").strip()
            or str(point.canonical_statement or "").strip()
            or any(str(part).strip() for part in point.topic_path)
        ):
            raise ValueError(
                f"{disposition} is non-writing and cannot carry canonical knowledge"
            )
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
    _reject_reused_mutating_targets(target_uses)
    for candidate_id, statements in candidate_written_statements.items():
        _validate_candidate_specificity(
            prepared,
            candidate_id=candidate_id,
            statements=statements,
        )
    normalized.sort(key=lambda item: prepared.candidate_ids.index(item["candidate_id"]))
    return {
        "version": "separated-v1",
        "candidate_ids": list(prepared.candidate_ids),
        "point_count": len(normalized),
        "points": normalized,
        "provider_candidate_ids": list(prepared.eligible_candidate_ids),
    }


def normalize_identical_replacements(
    prepared: SeparatedPreparedAssimilation,
    decision: Any,
) -> Any:
    """Turn exact no-op refine/replace decisions into confirmations.

    Providers decide semantic intent, but exact equality is a deterministic
    runtime fact. Normalizing it here prevents a harmless no-op from reaching
    the truth transaction as an invalid replacement while preserving genuine
    one-to-many replaces for the normal replacement path.
    """

    current_by_handle = {
        str(item.get("handle") or ""): item
        for item in prepared.manifest.get("current_truth") or []
        if isinstance(item, Mapping) and str(item.get("handle") or "")
    }
    if not current_by_handle:
        return decision

    payload = decision.model_dump(mode="json")
    changed = False
    for point in payload.get("points") or []:
        if point.get("disposition") not in {"refine", "replace"}:
            continue
        handles = [str(value) for value in point.get("matched_truth_handles") or []]
        if len(handles) != 1:
            continue
        target = current_by_handle.get(handles[0])
        if target is None:
            continue

        items = list(point.get("knowledge_items") or [])
        if items:
            # A one-to-many replace is never a confirmation, even when one
            # successor happens to equal the predecessor.
            if len(items) != 1:
                continue
            replacement = items[0]
            title = str(replacement.get("title") or "")
            statement = str(replacement.get("statement") or "")
            topic_path = list(replacement.get("topic_path") or [])
        else:
            title = str(point.get("canonical_title") or "")
            statement = str(point.get("canonical_statement") or "")
            topic_path = list(point.get("topic_path") or [])
        if not title or not statement or not topic_path:
            continue
        if (
            title != str(target.get("title") or "")
            or statement != str(target.get("statement") or "")
            or topic_path != list(target.get("topic_path") or [])
        ):
            continue

        point["disposition"] = "confirm"
        point["canonical_title"] = None
        point["canonical_statement"] = None
        point["topic_path"] = []
        point["knowledge_items"] = []
        changed = True

    if not changed:
        return decision
    return type(decision).model_validate(payload)


async def prepare_interactive_assimilation(
    backend: LocalMemoryBackend, *, project_name: str, project_root: str,
    candidate_ids: Sequence[str],
) -> dict[str, Any]:
    """Validate each manual proposal separately; retain unsafe points as work."""
    from harness_mem.autonomous.models import AssimilationDecision

    prepared = await prepare_separated_assimilation(
        backend, project_name=project_name, project_root=project_root,
        candidate_ids=candidate_ids,
    )
    points = [dict(point) for point in prepared.automatic_points]
    accepted = bool(points)
    errors: list[str] = []
    for candidate_id in prepared.eligible_candidate_ids:
        candidate = await backend.structured_store.knowledge_store.get_candidate(candidate_id)
        if candidate is None:
            # Missing work or a changed project/source is a shared safety error.
            raise ValueError("interactive candidate is no longer readable")
        try:
            proposal = await _interactive_proposal(backend, prepared, candidate)
            single = replace(prepared, candidate_ids=(candidate_id,),
                             eligible_candidate_ids=(candidate_id,), automatic_points=())
            validated = validate_separated_assimilation_decision(
                single, AssimilationDecision.model_validate({"points": [proposal]}),
            )
            points.extend(validated["points"])
            accepted = True
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
            reason = str(exc) if isinstance(exc, KnowledgeTargetError) else "这条内容的处理决定或写入内容还不完整，需要核对后再保存。"
            points.append(_automatic_point(candidate_id, answer_status="ANSWERED",
                                           disposition="defer", reason=reason))
    if not accepted and errors:
        # With no independently valid point, keep the existing retryable job.
        raise ValueError(errors[0])
    by_target: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        for target in point.get("matched_truth_ids") or []:
            by_target.setdefault(target, []).append(point)
    conflicting = {str(point["candidate_id"]) for uses in by_target.values()
                   if len(uses) > 1 and any(point["disposition"] in {"refine", "replace"} for point in uses)
                   for point in uses}
    points = [
        _automatic_point(str(point["candidate_id"]), answer_status="ANSWERED", disposition="defer",
                         reason="多项修改指向同一条旧记忆，原内容未改动；需要先确定采用哪项修改。")
        if point["candidate_id"] in conflicting else point for point in points
    ]
    points.sort(key=lambda point: prepared.candidate_ids.index(str(point["candidate_id"])))
    return {"version": "separated-v1", "candidate_ids": list(prepared.candidate_ids),
            "point_count": len(points), "points": points,
            "provider_candidate_ids": list(prepared.eligible_candidate_ids)}


async def _interactive_proposal(
    backend: LocalMemoryBackend, prepared: SeparatedPreparedAssimilation,
    candidate: KnowledgeCandidate,
) -> dict[str, Any]:
    disposition = str(candidate.assimilation_disposition or "").strip()
    reason = str(candidate.assimilation_reason or "").strip()
    if disposition not in _ASSIMILATION_DISPOSITIONS or len(reason) < 8:
        raise ValueError("interactive candidate needs an explicit processing decision and reason")
    targets = await resolve_knowledge_targets(
        backend.structured_store.knowledge_store, project_name=candidate.project_name,
        target_ids=candidate.assimilation_target_ids,
        target_knowledge=candidate.assimilation_targets,
    )
    # Confirmation can use its unchanged content directly; replacements must
    # name the old prose, not infer a target from the new content or title.
    if disposition == "confirm" and not targets:
        targets = await resolve_knowledge_targets(
            backend.structured_store.knowledge_store, project_name=candidate.project_name,
            target_knowledge=[{"statement": candidate.statement}],
        )
    if disposition in {"confirm", "refine", "replace"} and not targets:
        raise KnowledgeTargetError("还没有确定要修改的旧记忆，原内容未改动；请核对旧标题或内容。")
    handle_by_id = {truth_id: handle for handle, truth_id in prepared.truth_by_handle.items()}
    if any(target not in handle_by_id for target in targets):
        raise KnowledgeTargetError("要修改的旧记忆已变化，原内容未改动；请重新核对当前内容。")
    knowledge_items: list[dict[str, Any]] = []
    if disposition in _WRITING_DISPOSITIONS:
        if not candidate.canonical_title or not candidate.topic_path:
            raise ValueError("interactive writing candidate needs a title and project module")
        evidence = await backend.structured_store.knowledge_store.list_evidence(candidate.id)
        basis = evidence[0].evidence_basis if len(evidence) == 1 else None
        knowledge_items = [{"title": candidate.canonical_title, "statement": candidate.statement,
                            "topic_path": list(candidate.topic_path),
                            "claim_kind": "procedure" if candidate.candidate_type == "rule"
                            else "durable_preference" if basis == "user_statement"
                            else "implementation_fact"}]
    return {"candidate_id": candidate.id, "disposition": disposition,
            "matched_truth_handles": [handle_by_id[target] for target in targets],
            "knowledge_items": knowledge_items, "reason": reason}


async def apply_separated_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    candidate_ids: Sequence[str],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate and apply a separated plan; provider payloads are untrusted."""

    expected = [str(value) for value in candidate_ids]
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("separated assimilation candidates must be unique and non-empty")
    plan_candidate_ids = [str(value) for value in plan.get("candidate_ids") or []]
    if plan.get("version") != "separated-v1" or plan_candidate_ids != expected:
        raise ValueError("separated assimilation plan is not bound to these candidates")
    prepared = await prepare_separated_assimilation(
        backend,
        project_name=project_name,
        project_root=project_root,
        candidate_ids=expected,
    )
    provider_candidate_ids = [
        str(value) for value in plan.get("provider_candidate_ids") or []
    ]
    if (
        len(provider_candidate_ids) != len(set(provider_candidate_ids))
        or set(provider_candidate_ids) != set(prepared.eligible_candidate_ids)
    ):
        raise ValueError(
            "separated assimilation provider candidates no longer match the eligible set"
        )
    supplied_points = list(plan.get("points") or [])
    if plan.get("point_count") != len(supplied_points):
        raise ValueError("separated assimilation point_count does not match its points")
    points = _validate_apply_points(prepared, supplied_points)
    available_truth_ids = set(prepared.truth_by_handle.values())
    store = backend.structured_store.knowledge_store
    for point in points:
        for target_id in point.get("matched_truth_ids") or []:
            if target_id in available_truth_ids:
                continue
            if point["disposition"] not in {"refine", "replace"}:
                raise ValueError(
                    "separated assimilation target was not offered to the provider"
                )
            # A replaced target is allowed to reach the idempotent replay check.
            # A still-current target that was never in the bounded provider
            # manifest is an untrusted payload escalation and must fail here.
            if await store.get_entry(
                str(target_id),
                project_name=project_name,
                project_root=project_root,
            ) is not None:
                raise ValueError(
                    "separated assimilation target was not offered to the provider"
                )
    actual = [str(item.get("candidate_id") or "") for item in points]
    if set(actual) != set(expected):
        raise ValueError("separated assimilation plan does not cover this job's candidates")

    # Resolve the complete candidate/evidence set before the first mutation.
    # A disappearing later point must not leave earlier points committed while
    # the session is still reported as a successful complete review.
    candidates_by_id: dict[str, KnowledgeCandidate] = {}
    evidence_by_candidate: dict[str, KnowledgeEvidence] = {}
    expected_targets_by_candidate: dict[str, list[KnowledgeEntry]] = {}
    point_by_candidate = {point["candidate_id"]: point for point in points}
    for candidate_id in expected:
        candidate = await store.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"separated candidate is missing: {candidate_id}")
        if candidate.project_name != project_name:
            raise ValueError("separated assimilation candidate belongs to another project")
        point = point_by_candidate[candidate_id]
        committed_write = (candidate.status == "assimilated"
                           and point["disposition"] in _WRITING_DISPOSITIONS
                           and await is_committed_knowledge_point(backend, candidate=candidate, point=point))
        if (candidate.status == "assimilated" and point["disposition"] in _WRITING_DISPOSITIONS
                and not committed_write):
            raise ValueError("terminal candidate requires the exact normalized committed plan")
        candidates_by_id[candidate_id] = candidate
        evidence_by_candidate[candidate_id] = _job_bound_evidence(
            await store.list_evidence(candidate.id), candidate_id=candidate.id
        )
        evidence = evidence_by_candidate[candidate_id]
        if ("autonomous_final_scope_required" in evidence.verification_reason_codes
                and point["disposition"] in {"add", "refine", "replace", "confirm"}
                and not committed_write
                and final_scope_proof(final_scope_payload(prepared, point))
                not in evidence.verification_reason_codes):
            raise ValueError("final knowledge scope proof is missing or the normalized plan/target changed")
        if ("autonomous_final_scope_required" in evidence.verification_reason_codes
                and point["disposition"] in {"add", "refine", "replace", "confirm"}
                and not committed_write):
            expected_targets: list[KnowledgeEntry] = []
            for snapshot in final_scope_payload(prepared, point)["targets"]:
                current = await store.get_entry(snapshot["id"], project_name=project_name)
                if (current is None or current.statement != snapshot["statement"]
                        or current.title != snapshot["title"] or current.module_path != snapshot["topic_path"]
                        or (current.source_report.model_dump(mode="json", exclude={"text"})
                            if current.source_report is not None else None) != snapshot.get("source_report")):
                    raise ValueError("final knowledge scope target changed during preparation")
                expected_targets.append(current)
            expected_targets_by_candidate[candidate_id] = expected_targets

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
        candidate = candidates_by_id[candidate_id]
        evidence = evidence_by_candidate[candidate_id]
        subject = _subject(candidate, evidence)
        status = answer_gate_status(subject)
        disposition = str(point.get("disposition") or "reject")
        record_point = dict(point)
        if not record_point.get("knowledge_items"):
            record_point["claim_kind"] = _fallback_claim_kind(candidate, evidence)
        source_refs: list[ProjectKnowledgeSourceRef] = []
        resolved_root: Path | None = Path(project_root).expanduser().resolve() if project_root else None
        if disposition in {"add", "refine", "replace", "confirm"}:
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
            expected_predecessor_entries=expected_targets_by_candidate.get(candidate_id),
        )
        handoff_id: str | None = None
        if disposition in {"handoff", "defer", "conflict"}:
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
            "replaced_truth_ids": list(point.get("matched_truth_ids") or []) if disposition in {"refine", "replace"} else [],
            "reason": str(point.get("reason") or disposition),
            # The temporary evidence workspace is cleaned after finalization.
            # Keep its actual gate result in the existing job receipt so a
            # generic no-write reason cannot masquerade as purpose validation.
            "evidence_basis": evidence.evidence_basis,
            "verification_outcome": evidence.verification_outcome,
            "verification_reason_codes": list(evidence.verification_reason_codes),
            "verification_refs": [ref.sanitized().to_dict() for ref in evidence.verification_refs],
        }
        results.append(result)
        if disposition in {"add", "refine", "replace"}:
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


def _validate_apply_points(
    prepared: SeparatedPreparedAssimilation,
    supplied_points: Sequence[Any],
) -> list[dict[str, Any]]:
    """Normalize the wire plan against freshly derived evidence-gate results."""

    eligible = set(prepared.eligible_candidate_ids)
    automatic = {
        str(item["candidate_id"]): dict(item) for item in prepared.automatic_points
    }
    normalized: list[dict[str, Any]] = []
    target_uses: dict[str, list[str]] = {}
    for raw in supplied_points:
        if not isinstance(raw, Mapping):
            raise ValueError("separated assimilation point must be an object")
        point = dict(raw)
        candidate_id = str(point.get("candidate_id") or "")
        if candidate_id not in prepared.candidate_ids:
            raise ValueError("separated assimilation point references another candidate")
        expected_status = prepared.answer_status_by_candidate[candidate_id]
        disposition = str(point.get("disposition") or "")
        if disposition not in _ASSIMILATION_DISPOSITIONS:
            raise ValueError(f"unknown assimilation disposition: {disposition}")
        if candidate_id not in eligible:
            expected_point = automatic.get(candidate_id)
            if expected_point is None or (
                disposition != expected_point["disposition"]
                or str(point.get("answer_status") or "") != expected_status
            ):
                raise ValueError(
                    "separated assimilation cannot override the runtime Answer Gate"
                )
            normalized.append(expected_point)
            continue
        if expected_status != "ANSWERED" or point.get("answer_status") != "ANSWERED":
            raise ValueError("eligible assimilation points must remain ANSWERED")

        targets = [str(value) for value in point.get("matched_truth_ids") or []]
        if len(targets) != len(set(targets)):
            raise ValueError("assimilation point contains duplicate truth targets")
        if disposition == "confirm" and len(targets) != 1:
            raise ValueError("confirm requires exactly one current truth target")
        if disposition in {"refine", "replace"} and not targets:
            raise ValueError(f"{disposition} requires at least one current truth target")
        if disposition == "conflict" and len(targets) > 1:
            raise ValueError("conflict may reference at most one current truth target")
        if disposition in {"add", "no_write", "handoff", "defer", "reject"} and targets:
            raise ValueError(f"{disposition} must not target current truth")
        for target in targets:
            target_uses.setdefault(target, []).append(disposition)
        target_kinds = [str(value) for value in point.get("matched_truth_kinds") or []]
        if target_kinds and (
            len(target_kinds) != len(targets)
            or any(value != "knowledge_entry" for value in target_kinds)
        ):
            raise ValueError("separated assimilation target kinds are invalid")

        reason = str(point.get("reason") or "").strip()
        if not 8 <= len(reason) <= 1000:
            raise ValueError("assimilation reason must contain 8 to 1000 characters")
        knowledge_items = _validated_apply_knowledge_items(
            point,
            writes_truth=disposition in _WRITING_DISPOSITIONS,
        )
        report = _validate_report_authority(
            prepared, candidate_id=candidate_id, disposition=disposition, target_ids=targets,
        )
        _bind_report_items(report, knowledge_items, writes=disposition in _WRITING_DISPOSITIONS)
        normalized.append(
            {
                "candidate_id": candidate_id,
                "answer_status": expected_status,
                "disposition": disposition,
                "matched_truth_ids": targets,
                "matched_truth_kinds": ["knowledge_entry" for _target in targets],
                "canonical_title": None,
                "canonical_statement": None,
                "topic_path": [],
                "knowledge_items": knowledge_items,
                "reason": reason,
            }
        )
    _reject_reused_mutating_targets(target_uses)
    return normalized


def _reject_reused_mutating_targets(target_uses: Mapping[str, Sequence[str]]) -> None:
    """Prevent a plan from retiring truth and then reusing the stale target."""

    for dispositions in target_uses.values():
        if len(dispositions) > 1 and any(
            disposition in {"refine", "replace"} for disposition in dispositions
        ):
            raise ValueError(
                "one current truth target is reused across points that mutate it"
            )


def final_scope_payload(
    prepared: SeparatedPreparedAssimilation, point: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a scope verdict to the actual normalized items and target snapshots."""
    by_id = {
        prepared.truth_by_handle[item["handle"]]: {
            key: value for key, value in item.items() if key != "handle"
        }
        for item in prepared.manifest.get("current_truth") or []
    }
    targets = [str(value) for value in point.get("matched_truth_ids") or []]
    if any(target not in by_id for target in targets):
        raise ValueError("final scope target snapshot is unavailable")
    disposition = str(point["disposition"])
    items = _validated_apply_knowledge_items(
        point, writes_truth=disposition in _WRITING_DISPOSITIONS,
    )
    return {
        "candidate_id": str(point["candidate_id"]),
        "disposition": disposition,
        "knowledge_items": items,
        "targets": [{"id": target, **by_id[target]} for target in targets],
    }


def final_scope_proof(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Safe reason codes are at most 64 characters; retain 240 digest bits.
    return "fsv_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:60]


def _validated_apply_knowledge_items(
    point: Mapping[str, Any],
    *,
    writes_truth: bool,
) -> list[dict[str, Any]]:
    supplied = list(point.get("knowledge_items") or [])
    canonical_title = str(point.get("canonical_title") or "").strip()
    canonical_statement = str(point.get("canonical_statement") or "").strip()
    canonical_topic = list(point.get("topic_path") or [])
    if not writes_truth:
        if supplied or canonical_title or canonical_statement or canonical_topic:
            raise ValueError("non-writing assimilation cannot carry canonical knowledge")
        return []
    if supplied and (canonical_title or canonical_statement or canonical_topic):
        raise ValueError(
            "knowledge_items and legacy canonical fields cannot both write truth"
        )
    if not supplied:
        supplied = [
            {
                "title": canonical_title,
                "statement": canonical_statement,
                "topic_path": canonical_topic,
                "claim_kind": str(point.get("claim_kind") or "procedure"),
            }
        ]
    if not supplied:
        raise ValueError("knowledge-writing assimilation requires at least one item")
    normalized: list[dict[str, Any]] = []
    for raw in supplied:
        if not isinstance(raw, Mapping):
            raise ValueError("canonical knowledge item must be an object")
        item = _validate_canonical_knowledge_item(dict(raw))
        item["topic_path"] = validate_knowledge_module_path(item["topic_path"])
        normalized.append(item)
    return _normalize_split_knowledge_items(normalized)


def _normalize_split_knowledge_items(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse identical payloads, never infer subsumption from wording.

    Shared subject, approval qualifiers and punctuation do not prove that one
    independently verified fact is an umbrella for another. Semantic grouping
    belongs to the provider; local normalization must not erase distinct data.
    """

    normalized: list[dict[str, Any]] = []
    for item in items:
        value = dict(item)
        if value not in normalized:
            normalized.append(value)
    return normalized


def _validate_candidate_specificity(
    prepared: SeparatedPreparedAssimilation,
    *,
    candidate_id: str,
    statements: Sequence[str],
) -> None:
    """Prevent clean prose from dropping the verified point's mechanism."""

    projection = next(
        (
            item
            for item in prepared.manifest.get("verified_candidates") or []
            if isinstance(item, Mapping)
            and str(item.get("candidate_id") or "") == candidate_id
        ),
        None,
    )
    if projection is None:
        # Hand-built compatibility/test preparations may omit the provider
        # projection. Runtime preparations always include it and are checked.
        return
    source = str(projection.get("statement") or "").strip()
    output = " ".join(str(statement).strip() for statement in statements).strip()
    if not source or not output:
        raise ValueError("canonical knowledge cannot be checked against its candidate")

    source_identifiers = set(_candidate_required_identifiers(source))
    output_identifiers = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", output)
    }
    missing = sorted(source_identifiers - output_identifiers)
    if missing:
        raise ValueError(
            "canonical knowledge drops distinctive candidate terms: "
            + ", ".join(missing)
        )

    positive_mechanism = re.split(
        r"(?:而不能|而不是|而非|rather than|instead of)",
        source,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(positive_mechanism) == 2:
        mechanism_terms = _knowledge_similarity_terms(positive_mechanism[0])
        output_terms = _knowledge_similarity_terms(output)
        mechanism_coverage = len(mechanism_terms & output_terms) / max(
            1, len(mechanism_terms)
        )
        if mechanism_coverage < 0.25:
            raise ValueError(
                "canonical knowledge drops the candidate's positive mechanism "
                f"(lexical coverage {mechanism_coverage:.2f})"
            )

    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", source):
        source_terms = _knowledge_similarity_terms(source)
        output_terms = _knowledge_similarity_terms(output)
        coverage = len(source_terms & output_terms) / max(1, len(source_terms))
        if coverage < 0.30:
            raise ValueError(
                "canonical knowledge drops the candidate's defining mechanism "
                f"(lexical coverage {coverage:.2f})"
            )


def _validate_canonical_knowledge_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {"title", "statement", "topic_path", "claim_kind"}
    if set(raw) != allowed_keys:
        raise ValueError("canonical knowledge item has an invalid schema")
    title = " ".join(str(raw.get("title") or "").split())
    statement = " ".join(str(raw.get("statement") or "").split())
    topic_value = raw.get("topic_path")
    claim_kind = str(raw.get("claim_kind") or "")
    if not title or not statement:
        raise ValueError("canonical knowledge title or statement is invalid")
    if not isinstance(topic_value, list) or not topic_value:
        raise ValueError("canonical knowledge topic_path is invalid")
    if any(not isinstance(part, str) or not part.strip() for part in topic_value):
        raise ValueError("canonical knowledge topic_path is invalid")
    if claim_kind not in {
        "design_requirement",
        "implementation_fact",
        "durable_preference",
        "procedure",
        "source_report",
    }:
        raise ValueError("canonical knowledge claim_kind is invalid")
    try:
        statement = validate_atomic_knowledge_statement(statement)
    except ValueError as exc:
        raise ValueError(
            f"canonical knowledge statement is not atomic or natural: {exc}"
        ) from exc
    return {
        "title": title,
        "statement": statement,
        "topic_path": [part.strip() for part in topic_value],
        "claim_kind": claim_kind,
    }


async def separated_job_candidate_ids(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str,
    include_candidate_ids: Sequence[str] = (),
    include_reviewed: bool = False,
) -> list[str]:
    """Return pending and explicitly replayed candidates bound to this job.

    A separated assimilation applies one point at a time.  If a later point
    fails, earlier candidates may already be terminal even though the distill
    job is not.  ``include_candidate_ids`` lets the retry prove those terminal
    candidates still belong to this job without pulling deferred candidates
    from an older extraction attempt back into the active plan.
    ``include_reviewed`` is a diagnostic lookup for missing-plan errors, not
    permission to assimilate those candidates automatically.
    """

    store = backend.structured_store.knowledge_store
    included = {str(value) for value in include_candidate_ids}
    matches: list[str] = []
    for candidate in await store.list_candidates(project_name):
        if (candidate.status != "pending" and candidate.id not in included
                and not (include_reviewed and candidate.status == "assimilated")):
            continue
        if any(
            evidence.distill_job_id == distill_job_id
            for evidence in await store.list_evidence(candidate.id)
        ):
            matches.append(candidate.id)
    return sorted(matches)


async def is_committed_job_replay(
    backend: LocalMemoryBackend, *, project_name: str, distill_job_id: str,
    plan: Mapping[str, Any],
) -> bool:
    """Only exact already-committed writes may enter public replay unleased.

    This is not permission for a new write. Normal finalization still claims
    its lease and revalidates source, current rows, predecessor absence and
    ordinary search before producing a Note.
    """
    if plan.get("version") != "separated-v1":
        return False
    ids = list(plan.get("candidate_ids") or [])
    points = list(plan.get("points") or [])
    if not ids or len(ids) != len(set(ids)) or len(points) != len(ids):
        return False
    if any(not isinstance(point, Mapping) for point in points):
        return False
    if {point.get("candidate_id") for point in points} != set(ids):
        return False
    store = backend.structured_store.knowledge_store
    for point in points:
        candidate = await store.get_candidate(str(point["candidate_id"]))
        if candidate is None or candidate.project_name != project_name:
            return False
        evidence = await store.list_evidence(candidate.id)
        if len(evidence) != 1 or evidence[0].distill_job_id != distill_job_id:
            return False
        try:
            normalized = {
                **point,
                "knowledge_items": _validated_apply_knowledge_items(point, writes_truth=True),
                "reason": str(point.get("reason") or "").strip(),
            }
            if not await is_committed_knowledge_point(backend, candidate=candidate, point=normalized):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def _statement(arguments: Mapping[str, Any], *, kind: str) -> str:
    if kind == "memory":
        statement = str(arguments.get("content") or "").strip()
    elif kind == "rule":
        trigger = str(arguments.get("trigger") or "").strip().rstrip("，,:：")
        pattern = str(arguments.get("pattern") or "").strip()
        separator = "：" if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", trigger) else ": "
        statement = f"{trigger}{separator}{pattern}".strip()
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
    if value not in {"repository", "user_statement", "transcript", "source_report"}:
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
        statement=candidate.statement,
        source_report=candidate.source_report,
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
    """Use the verified future scope, not whether a statement is a correction."""
    return bool({"session_only_not_durable", "source_use_task_context"}.intersection(
        evidence.verification_reason_codes
    ))


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
        "required_terms": _candidate_required_identifiers(candidate.statement),
        "evidence_basis": evidence.evidence_basis,
        "verification_reason_codes": list(evidence.verification_reason_codes),
        "answer_status": answer_gate_status(subject),
        **({"source_report": candidate.source_report.model_dump(mode="json", exclude={"text"})}
           if candidate.source_report is not None else {}),
    }


def _candidate_required_identifiers(statement: str) -> list[str]:
    """Expose exact technical identifiers that canonical prose must retain."""

    stopwords = {
        "and",
        "current",
        "from",
        "into",
        "knowledge",
        "memory",
        "must",
        "not",
        "only",
        "project",
        "rely",
        "relies",
        "rule",
        "should",
        "that",
        "the",
        "this",
        "use",
        "uses",
        "using",
        "when",
        "with",
    }
    return sorted(
        {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", statement)
            if token.casefold() not in stopwords
        }
    )


def _knowledge_similarity_terms(text: str) -> set[str]:
    """Tokenize mixed English/CJK knowledge for bounded truth selection.

    Whitespace splitting treats an entire Chinese sentence as one token, which
    made relevant current truth lose every lexical tie and fall outside the
    manifest cap. Short CJK n-grams preserve deterministic local matching
    without introducing another model call or retrieval authority.
    """

    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+", text.casefold()):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", token):
            if len(token) <= 3:
                terms.add(token)
            for width in (2, 3):
                terms.update(
                    token[index : index + width]
                    for index in range(len(token) - width + 1)
                )
        elif len(token) >= 3:
            terms.add(token)
    return terms


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
    candidate_terms = [
        _knowledge_similarity_terms(candidate.statement) for candidate in candidates
    ]

    def relevance(entry: KnowledgeEntry) -> tuple[int, float]:
        entry_terms = _knowledge_similarity_terms(
            " ".join([entry.title, entry.statement, *entry.module_path])
        )
        scores = []
        for terms in candidate_terms:
            overlap = len(terms & entry_terms)
            denominator = min(len(terms), len(entry_terms))
            scores.append((overlap, overlap / denominator if denominator else 0.0))
        return max(scores, default=(0, 0.0))

    relevance_by_id = {entry.id: relevance(entry) for entry in entries}
    entries.sort(
        key=lambda entry: (
            -relevance_by_id[entry.id][0],
            -relevance_by_id[entry.id][1],
            entry.id,
        )
    )
    handles: dict[str, str] = {}
    projected: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, 1):
        handle = f"T{index}"
        handles[handle] = entry.id
        projected.append(
            {
                "handle": handle,
                "kind": "knowledge_entry",
                "title": entry.title,
                "statement": entry.statement,
                "topic_path": list(entry.module_path),
                **({"source_report": entry.source_report.model_dump(mode="json", exclude={"text"})}
                   if entry.source_report is not None else {}),
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
        if candidate.source_report is not None and (
            existing.summary != candidate.source_report.render_statement()
            or existing.context.get("source_report") != candidate.source_report.model_dump(mode="json")
        ):
            raise ValueError("existing source-report handoff lost its attribution boundary")
        return existing.id
    statement = (
        candidate.source_report.render_statement()
        if candidate.source_report is not None
        else str(point.get("canonical_statement") or candidate.statement)
    )
    handoff = TaskHandoff(
        id=handoff_id,
        project_name=candidate.project_name,
        task_id=f"assimilation:{candidate.id}",
        summary=statement,
        status="in_progress",
        next_steps=[f"还没保存：{statement}。{point['reason']}" if point.get("disposition") == "defer" else statement],
        context={
            "distill_job_id": evidence.distill_job_id,
            "candidate_id": candidate.id,
            **({"source_report": candidate.source_report.model_dump(mode="json")}
               if candidate.source_report is not None else {}),
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

    if candidate.source_report is not None:
        return "source_report"
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
    "admit_separated_candidate",
    "apply_separated_assimilation",
    "create_separated_candidates",
    "normalize_identical_replacements",
    "prepare_separated_assimilation",
    "separated_job_candidate_ids",
    "validate_separated_assimilation_decision",
]
