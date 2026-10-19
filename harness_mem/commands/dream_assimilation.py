"""Trusted application of bounded Dream comparison decisions.

Dream works over already-governed current knowledge rather than over a
session-distill job. Its automatic maintenance plan is derived from completed
source verification, then the runtime rechecks the real sources and directly
confirms or retires current knowledge. The comparative decision validator is
retained for existing callers; automatic Dream does not request another model
decision over dispositions that verification has already constrained.

The caller keeps reopened source text in memory.  It is present in the
provider manifest only for the immediate no-tool semantic call and is never
stored in a candidate, decision, Dream receipt, or current knowledge row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast
from uuid import NAMESPACE_URL, uuid5

from harness_mem.autonomous.models import (
    AssimilationDecision, CandidateVerificationPoint, verification_scope_status,
)
from harness_mem.commands.evidence_admission import validate_knowledge_sources
from harness_mem.commands.knowledge_assimilation import (
    delete_current_knowledge,
    record_assimilation_result,
)
from harness_mem.commands.separated_assimilation import (
    validate_knowledge_module_path,
)
from harness_mem.core.schemas import (
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeSource,
    ProjectKnowledgeSourceRef,
)
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


DreamSemanticSupport = Literal["supported", "partial", "contradicted"]
DreamFutureScope = Literal["durable", "session_only", "unclear"]
DreamSignalKind = Literal["duplicate", "conflict", "stale", "feedback"]


@dataclass(frozen=True)
class DreamAssimilationCandidate:
    """One current knowledge row plus its completed source recheck."""

    candidate_id: str
    entry: KnowledgeEntry
    sources: tuple[KnowledgeSource, ...]
    semantic_support: DreamSemanticSupport
    future_scope: DreamFutureScope
    verification_reason: str
    source_excerpts: tuple[dict[str, str], ...]
    scope_verification: CandidateVerificationPoint | None = None


def dream_scope_text(entry: KnowledgeEntry) -> str:
    """Classify report prose without treating its generated attribution as a claim."""
    report = entry.source_report
    if report is None:
        return entry.title + "\n" + entry.statement
    if entry.title != report.render_title() or entry.statement != report.render_statement():
        raise ValueError("Dream report rendering does not match its bound attribution")
    return report.text


def dream_temporary_retirement_allowed(
    entry: KnowledgeEntry, point: CandidateVerificationPoint | None,
) -> bool:
    """Only an explicit complete disposable partition may retire supported text."""
    return bool(
        point is not None and point.semantic_support == "supported"
        and verification_scope_status(point, dream_scope_text(entry)) == "source_scope_session_only"
        # A substantive unit remains meaningful even when its later use is
        # uncertain. Only an explicit inventory with no such claim may retire
        # the whole row as disposable context.
        and not point.claim_units
        and all(segment.content_role == "temporary_context"
                and segment.source_use == "task_context" and segment.future_scope == "session_only"
                and segment.source_support == "supported"
                for segment in point.scope_segments)
    )


def _retained_report_text(point: CandidateVerificationPoint) -> str:
    units = _standalone_durable_units(point, body_start=0)
    if len(units) != 1:
        raise ValueError("Dream report refinement requires one complete continuous claim unit")
    return units[0][0]


def _standalone_durable_units(
    point: CandidateVerificationPoint, *, body_start: int,
) -> list[tuple[str, str, frozenset[int]]]:
    """Read the verifier's joint proofs; never infer standalone from fragments."""
    segments = point.scope_segments
    starts: list[int] = []
    offset = 0
    for segment in segments:
        starts.append(offset)
        offset += len(segment.text)
    retained: list[tuple[str, str, frozenset[int]]] = []
    occupied: set[int] = set()
    for unit in point.claim_units:
        first, end = unit.first_segment, unit.end_segment_exclusive
        if not (0 <= first < end <= len(segments)):
            return []
        if (unit.source_support != "supported" or not unit.standalone
                or unit.future_scope != "durable"
                or unit.source_use not in {"standing_decision", "reusable_knowledge"}):
            continue
        if starts[first] < body_start:
            # The original title is checked separately and cannot become body.
            continue
        selected = segments[first:end]
        substantive = [part for part in selected if part.text.strip()]
        if (not substantive or not any(part.content_role == "claim" for part in substantive)
                or any(part.source_support != "supported"
                       or part.content_role not in {"claim", "qualifier"}
                       for part in substantive)):
            return []
        indexes = frozenset(range(first, end))
        if occupied.intersection(indexes):
            return []
        occupied.update(indexes)
        # A unit is an original continuous range, never a collection assembled
        # across a temporary or unknown clause.
        text = "".join(part.text for part in selected).strip()
        if not text:
            return []
        retained.append((text, unit.source_use, indexes))
    return sorted(retained, key=lambda row: min(row[2]))


@dataclass(frozen=True)
class DreamPreparedAssimilation:
    """A bounded project-local comparative assimilation manifest."""

    project_name: str
    project_root: Path
    run_id: str
    signal_kind: DreamSignalKind
    candidates: tuple[DreamAssimilationCandidate, ...]
    truth_by_handle: dict[str, str]
    manifest: dict[str, Any]


def prepare_dream_assimilation(
    *,
    project_name: str,
    project_root: str | Path,
    run_id: str,
    signal_kind: DreamSignalKind,
    candidates: Sequence[DreamAssimilationCandidate],
) -> DreamPreparedAssimilation:
    """Build the only provider-visible comparison manifest for a Dream group."""

    if not candidates:
        raise ValueError("Dream assimilation needs at least one verified candidate")
    root = Path(project_root).expanduser().resolve()
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Dream assimilation candidates must be unique")
    if any(candidate.entry.project_name != project_name for candidate in candidates):
        raise ValueError("Dream assimilation candidate crosses projects")

    truth_by_handle: dict[str, str] = {}
    current_truth: list[dict[str, Any]] = []
    verified_candidates: list[dict[str, Any]] = []
    source_excerpts: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates, 1):
        handle = f"T{index}"
        truth_by_handle[handle] = candidate.entry.id
        current_truth.append(
            {
                "handle": handle,
                "kind": "knowledge_entry",
                "title": candidate.entry.title,
                "statement": candidate.entry.statement,
                "topic_path": list(candidate.entry.module_path),
                **({"source_report": candidate.entry.source_report.model_dump(mode="json", exclude={"text"})}
                   if candidate.entry.source_report is not None else {}),
            }
        )
        verified_candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "own_truth_handle": handle,
                "statement": candidate.entry.statement,
                "required_terms": _required_terms(candidate.entry.statement),
                "semantic_support": candidate.semantic_support,
                "future_scope": candidate.future_scope,
                "verification_reason": candidate.verification_reason,
            }
        )
        source_excerpts.extend(
            {
                "candidate_id": candidate.candidate_id,
                "source_kind": excerpt["source_kind"],
                "content": excerpt["content"],
            }
            for excerpt in candidate.source_excerpts
        )

    return DreamPreparedAssimilation(
        project_name=project_name,
        project_root=root,
        run_id=run_id,
        signal_kind=signal_kind,
        candidates=tuple(candidates),
        truth_by_handle=truth_by_handle,
        manifest={
            "contract_version": "dream-source-assimilation-v1",
            "project_name": project_name,
            "dream_signal": signal_kind,
            "verified_candidates": verified_candidates,
            "current_truth": current_truth,
            "source_excerpts": source_excerpts,
        },
    )


def build_dream_maintenance_plan(
    prepared: DreamPreparedAssimilation,
) -> list[dict[str, Any]]:
    """Derive maintenance from completed verification, not a second model vote.

    Source reopening has already admitted every supplied candidate. Unclear
    or partial semantic results remain unchanged; a supported durable row is
    refreshed, and an explicitly contradicted row may retire only itself.
    Only complete disposable content-role partitions may retire temporary rows.
    A complete mixed partition may retain verbatim, independently
    complete durable claims; it cannot manufacture rewritten knowledge.
    """

    plan: list[dict[str, Any]] = []
    for candidate in prepared.candidates:
        disposition = "no_write"
        target_ids: list[str] = []
        reason = candidate.verification_reason
        retained_items = _verified_durable_scope_items(candidate)
        if retained_items:
            disposition = "refine"
            target_ids = [candidate.entry.id]
        elif candidate.future_scope != "unclear":
            if candidate.semantic_support == "supported":
                if candidate.future_scope == "session_only":
                    if dream_temporary_retirement_allowed(candidate.entry, candidate.scope_verification):
                        disposition = "reject"
                        target_ids = [candidate.entry.id]
                    else:
                        reason = (
                            "The complete content-role partition has not established "
                            "that all supported content is disposable; scope remains unresolved."
                        )
                elif candidate.future_scope == "durable":
                    disposition = "confirm"
                    target_ids = [candidate.entry.id]
                    if prepared.signal_kind == "duplicate":
                        survivors = [
                            other for other in prepared.candidates
                            if other.semantic_support == "supported"
                            and other.future_scope == "durable"
                            and other.entry.source_report == candidate.entry.source_report
                            and other.entry.statement == candidate.entry.statement
                        ]
                        survivor = min(survivors, key=lambda item: item.entry.id)
                        if survivor.entry.id != candidate.entry.id:
                            disposition = "reject"
                            target_ids = [survivor.entry.id]
            elif candidate.semantic_support == "contradicted":
                disposition = "reject"
                target_ids = [candidate.entry.id]
        plan.append({
            "candidate_id": candidate.candidate_id,
            "entry_id": candidate.entry.id,
            "disposition": disposition,
            "matched_truth_ids": target_ids,
            "canonical_title": None,
            "canonical_statement": None,
            "topic_path": [],
            "knowledge_items": retained_items,
            "reason": reason,
        })
    return plan


def _verified_durable_scope_items(candidate: DreamAssimilationCandidate) -> list[dict[str, Any]]:
    """Retain complete source-supported units from an existing mixed row.

    The original point may remain partial. No new extraction candidate becomes
    verified through this maintenance-only literal derivation.
    """
    point = candidate.scope_verification
    if (point is None
            or candidate.semantic_support not in {"supported", "partial"}
            or point.semantic_support != candidate.semantic_support
            or not point.scope_segments
            or "".join(part.text for part in point.scope_segments) != dream_scope_text(candidate.entry)):
        return []
    body_start = len(candidate.entry.title) + 1 if candidate.entry.source_report is None else 0
    units = _standalone_durable_units(point, body_start=body_start)
    if not units or (candidate.entry.source_report is not None and len(units) != 1):
        return []
    retained_indexes = frozenset(index for _text, _use, indexes in units for index in indexes)
    removed = False
    offset = 0
    for index, segment in enumerate(point.scope_segments):
        end = offset + len(segment.text)
        if offset < body_start:
            if (end > body_start or segment.future_scope != "durable"
                    or segment.source_use not in {"standing_decision", "reusable_knowledge"}
                    or segment.content_role not in {"claim", "qualifier"}
                    or segment.source_support != "supported"):
                return []
            offset = end
            continue
        offset = end
        if index in retained_indexes or not segment.text.strip():
            continue
        # A claim-unit inventory cannot disagree with a disposable segment.
        # In particular, an uncertain or session-scoped constraint is not
        # silently discarded because it was also labelled temporary.
        if any(unit.first_segment <= index < unit.end_segment_exclusive
               and unit.source_support not in {"unsupported", "contradicted"}
               for unit in point.claim_units):
            return []
        temporary = (segment.content_role == "temporary_context"
            and segment.source_support == "supported"
            and segment.source_use == "task_context" and segment.future_scope == "session_only")
        unsupported = (point.semantic_support == "partial"
            and segment.source_support in {"unsupported", "contradicted"}
            and segment.content_role == "claim" and segment.standalone)
        if not temporary and not unsupported:
            # Unknown text and detached qualifiers stay in current knowledge.
            return []
        removed = True
    if not removed:
        return []
    if candidate.entry.source_report is not None:
        report = candidate.entry.source_report.model_copy(update={
            "text": _retained_report_text(point),
        })
        items = [{
            "title": report.render_title(), "statement": report.render_statement(),
            "topic_path": list(candidate.entry.module_path), "claim_kind": "source_report",
        }]
    else:
        items = [{
            "title": candidate.entry.title, "statement": text,
            "topic_path": list(candidate.entry.module_path),
            "claim_kind": "design_requirement" if source_use == "standing_decision" else "procedure",
        } for text, source_use, _indexes in units]
    try:
        _validate_writing_items(knowledge_items=items, canonical_title=None,
                                canonical_statement=None, topic_path=[], disposition="refine")
    except ValueError:
        return []
    return items


def validate_dream_assimilation_decision(
    prepared: DreamPreparedAssimilation,
    decision: AssimilationDecision,
) -> list[dict[str, Any]]:
    """Bind an untrusted provider decision to rechecked current knowledge.

    A Dream ``reject`` has deliberately narrower semantics than a session
    candidate rejection: it can retire *its own* contradicted row,
    or an exact duplicate whose equivalent survivor is named
    by the provider. Partial or unclear evidence cannot retire current truth.
    """

    points = list(decision.points)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in prepared.candidates}
    point_ids = [str(point.candidate_id) for point in points]
    if len(point_ids) != len(set(point_ids)):
        raise ValueError("Dream assimilation decision contains duplicate candidates")
    if set(point_ids) != set(candidate_by_id):
        raise ValueError("Dream assimilation decision must cover every candidate once")

    entry_by_id = {candidate.entry.id: candidate.entry for candidate in prepared.candidates}
    normalized: list[dict[str, Any]] = []
    for point in points:
        candidate = candidate_by_id[str(point.candidate_id)]
        own_handle = _own_handle(prepared, candidate.entry.id)
        handles = [str(handle) for handle in point.matched_truth_handles]
        if len(handles) != len(set(handles)):
            raise ValueError("Dream assimilation point contains duplicate truth handles")
        if any(handle not in prepared.truth_by_handle for handle in handles):
            raise ValueError("Dream assimilation point references an unavailable truth handle")
        disposition = str(point.disposition)
        if candidate.entry.source_report is not None and disposition == "replace":
            raise ValueError("source-report authority cannot be rewritten by Dream")
        for handle in handles:
            target_entry = entry_by_id[prepared.truth_by_handle[handle]]
            if ((candidate.entry.source_report is None) != (target_entry.source_report is None)):
                raise ValueError("Dream cannot cross source-report and fact authority boundaries")
            if (candidate.entry.source_report is not None
                    and candidate.entry.source_report != target_entry.source_report):
                raise ValueError("Dream cannot merge reports with distinct source attribution")
        if disposition not in {
            "confirm",
            "refine",
            "replace",
            "no_write",
            "defer",
            "conflict",
            "reject",
        }:
            raise ValueError("Dream assimilation may not add knowledge or create a handoff")
        reason = str(point.reason or "").strip()
        if not 8 <= len(reason) <= 1000:
            raise ValueError("Dream assimilation reason must contain 8 to 1000 characters")

        knowledge_items = [item.model_dump() for item in point.knowledge_items]
        if disposition == "confirm":
            if handles != [own_handle]:
                raise ValueError("Dream confirm must target its own current truth")
        elif disposition in {"refine", "replace"}:
            if not handles or own_handle not in handles:
                raise ValueError(
                    f"Dream {disposition} must include its own current truth"
                )
        elif disposition == "reject":
            if len(handles) != 1:
                raise ValueError("Dream reject must name one current truth handle")
        elif handles:
            raise ValueError(f"Dream {disposition} must not target current truth")

        if disposition in {"refine", "replace"}:
            _validate_writing_items(
                knowledge_items=knowledge_items,
                canonical_title=point.canonical_title,
                canonical_statement=point.canonical_statement,
                topic_path=point.topic_path,
                disposition=disposition,
            )
        else:
            # These actions never write text. Ignore redundant proposals rather
            # than interpreting them or rejecting an otherwise safe outcome.
            knowledge_items = []

        support = candidate.semantic_support
        durable = candidate.future_scope == "durable"
        retained_items = _verified_durable_scope_items(candidate)
        if disposition == "refine" and retained_items:
            if handles != [own_handle] or knowledge_items != retained_items:
                raise ValueError("Dream refinement must preserve its exact verified literal claims")
        elif support == "supported" and durable:
            if disposition == "reject":
                survivor_id = prepared.truth_by_handle[handles[0]]
                survivor = entry_by_id[survivor_id]
                if (
                    prepared.signal_kind != "duplicate"
                    or survivor_id == candidate.entry.id
                    or not _same_statement(candidate.entry.statement, survivor.statement)
                ):
                    raise ValueError(
                        "Dream may retire supported knowledge only as an exact duplicate"
                    )
            elif disposition not in {"confirm", "no_write", "defer", "conflict"}:
                raise ValueError("supported Dream knowledge cannot be rewritten")
        elif support == "supported" and candidate.future_scope == "session_only":
            if disposition == "reject" and (
                handles != [own_handle]
                or not dream_temporary_retirement_allowed(candidate.entry, candidate.scope_verification)
            ):
                raise ValueError("Dream retirement requires a complete disposable content partition")
            if disposition not in {"reject", "no_write", "defer", "conflict"}:
                raise ValueError("session-only scope cannot authorize a Dream truth mutation")
        elif support == "contradicted":
            if disposition in {"confirm"}:
                raise ValueError("contradicted Dream knowledge cannot be confirmed")
            if disposition == "reject" and handles != [own_handle]:
                raise ValueError("contradicted Dream knowledge may retire only itself")
        elif disposition not in {"no_write", "defer", "conflict"}:
            raise ValueError("incomplete Dream evidence cannot mutate current knowledge")

        normalized.append(
            {
                "candidate_id": candidate.candidate_id,
                "entry_id": candidate.entry.id,
                "disposition": disposition,
                "matched_truth_ids": [prepared.truth_by_handle[handle] for handle in handles],
                "canonical_title": point.canonical_title if disposition in {"refine", "replace"} else None,
                "canonical_statement": point.canonical_statement if disposition in {"refine", "replace"} else None,
                "topic_path": list(point.topic_path) if disposition in {"refine", "replace"} else [],
                "knowledge_items": knowledge_items,
                "reason": reason,
            }
        )
    normalized.sort(key=lambda item: candidate_ids_in_order(prepared).index(item["candidate_id"]))
    return normalized


async def apply_dream_assimilation(
    backend: LocalMemoryBackend,
    *,
    prepared: DreamPreparedAssimilation,
    plan: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Recheck sources again, then apply each allowed Dream change.

    Each write uses the normal current-knowledge path. Confirmation freshness
    changes no statement and may advance a reopened source digest only after
    the second byte-level check succeeds.
    """

    candidates = {candidate.candidate_id: candidate for candidate in prepared.candidates}
    if (len(plan) != len(candidates)
            or {str(point.get("candidate_id") or "") for point in plan} != set(candidates)):
        raise ValueError("Dream assimilation plan is not bound to its candidates")
    derived = {point["candidate_id"]: point for point in build_dream_maintenance_plan(prepared)}
    for point in plan:
        candidate = candidates[str(point["candidate_id"])]
        if (str(point.get("disposition")) == "reject"
                and candidate.semantic_support == "supported"
                and candidate.future_scope == "session_only"
                and not dream_temporary_retirement_allowed(candidate.entry, candidate.scope_verification)):
            raise ValueError("Dream retirement requires a complete disposable content partition")
        if str(point.get("disposition")) in {"refine", "replace"}:
            expected = derived[str(point["candidate_id"])]
            if expected["disposition"] != "refine" or dict(point) != expected:
                raise ValueError("Dream refinement must exactly retain its verified standalone durable segments")
    store = backend.structured_store.knowledge_store
    outcomes: list[dict[str, Any]] = []
    for point in plan:
        candidate = candidates[str(point["candidate_id"])]
        disposition = str(point["disposition"])
        if disposition in {"no_write", "defer", "conflict"}:
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "rejected",
                    "reason": str(point["reason"]),
                }
            )
            continue
        target_candidates = [candidate]
        if disposition in {"refine", "replace", "reject"}:
            target_ids = [str(value) for value in point.get("matched_truth_ids") or []]
            by_id = {item.entry.id: item for item in prepared.candidates}
            target_candidates.extend(
                by_id[target_id] for target_id in target_ids
                if target_id != candidate.entry.id
            )
        current_targets = [
            await store.get_entry(target.entry.id, project_name=prepared.project_name)
            for target in target_candidates
        ]
        if any(
            current is None
            or current.statement != target.entry.statement
            or current.title != target.entry.title
            or current.module_path != target.entry.module_path
            or current.source_report != target.entry.source_report
            for target, current in zip(target_candidates, current_targets)
        ):
            outcomes.append({
                "candidate_id": candidate.candidate_id,
                "entry_id": candidate.entry.id,
                "status": "source_changed",
                "reason": "Dream current knowledge changed after its source recheck.",
            })
            continue
        validations = [
            await validate_knowledge_sources(
                backend,
                project_name=prepared.project_name,
                sources=target.sources,
                project_root=prepared.project_root,
            )
            for target in target_candidates
        ]
        validation = validations[0]
        if any(item.verification_outcome != "verified" for item in validations):
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "source_changed",
                    "reason": "Dream source changed before its truth transaction.",
                }
            )
            continue
        if disposition == "confirm":
            verified_at = validation.verified_at or datetime.now().astimezone()
            try:
                await store.refresh_entry_verification(
                    project_name=prepared.project_name,
                    entry_id=candidate.entry.id,
                    verified_at=verified_at,
                    refresh_id=f"dream:{prepared.run_id}:{candidate.candidate_id}:confirm",
                    refreshed_sources=candidate.sources,
                    expected_entry=current_targets[0],
                )
            except CanonicalTransactionPreconditionError:
                outcomes.append({
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "source_changed",
                    "reason": "Dream confirmation target changed before commit.",
                })
                continue
            refreshed = await store.get_entry(
                candidate.entry.id, project_name=prepared.project_name,
            )
            if (
                refreshed is None
                or refreshed.statement != candidate.entry.statement
                or refreshed.source_report != candidate.entry.source_report
                or refreshed.verified_at != verified_at
            ):
                raise RuntimeError("Dream confirmation readback did not match verified knowledge")
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "applied",
                    "truth_change": "verification_refreshed",
                    "reason": str(point["reason"]),
                }
            )
            continue
        if disposition == "reject":
            try:
                await delete_current_knowledge(
                    backend,
                    project_name=prepared.project_name,
                    target_knowledge_ids=[candidate.entry.id],
                    expected_entry=current_targets[0],
                    retained_entries=[entry for entry in current_targets[1:] if entry is not None],
                )
            except CanonicalTransactionPreconditionError:
                outcomes.append({
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "source_changed",
                    "reason": "Dream deletion target or retained knowledge changed before commit.",
                })
                continue
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "applied",
                    "truth_change": "deleted",
                    "reason": str(point["reason"]),
                }
            )
            continue

        if disposition not in {"refine", "replace"}:  # pragma: no cover - validator owns this.
            raise ValueError(f"unsupported Dream assimilation disposition: {disposition}")
        retained_report = candidate.entry.source_report
        if retained_report is not None:
            retained_report = retained_report.model_copy(update={
                "text": _retained_report_text(cast(CandidateVerificationPoint, candidate.scope_verification)),
            })
        workspace_candidate = KnowledgeCandidate(
            id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"harness-mem:dream-candidate:{prepared.run_id}:{candidate.entry.id}",
                )
            ),
            project_name=prepared.project_name,
            candidate_type="memory",
            statement=retained_report.text if retained_report else candidate.entry.statement,
            source_report=retained_report,
        )
        record_point = {
            **dict(point),
            "verified_at": validation.verified_at,
            "matched_truth_kinds": [
                "knowledge_entry" for _target in target_candidates
            ],
        }
        source_refs = [
            ref
            for target in target_candidates
            for ref in _source_refs(target.sources)
        ]
        try:
            truth_ids = await record_assimilation_result(
                backend,
                candidate=workspace_candidate,
                point=record_point,
                project_root=prepared.project_root,
                source_refs=source_refs,
                expected_predecessor_entries=[entry for entry in current_targets if entry is not None],
            )
        except CanonicalTransactionPreconditionError:
            outcomes.append({
                "candidate_id": candidate.candidate_id, "entry_id": candidate.entry.id,
                "status": "source_changed", "reason": "Dream refinement target changed before commit.",
            })
            continue
        await store.cleanup_candidate(workspace_candidate.id)
        outcomes.append(
            {
                "candidate_id": candidate.candidate_id,
                "entry_id": candidate.entry.id,
                "status": "applied",
                "truth_change": disposition,
                "truth_ids": truth_ids,
                "reason": str(point["reason"]),
            }
        )
    return outcomes


def candidate_ids_in_order(prepared: DreamPreparedAssimilation) -> list[str]:
    return [candidate.candidate_id for candidate in prepared.candidates]


def _own_handle(prepared: DreamPreparedAssimilation, entry_id: str) -> str:
    for handle, truth_id in prepared.truth_by_handle.items():
        if truth_id == entry_id:
            return handle
    raise ValueError("Dream candidate is not a supplied current truth")


def _source_refs(sources: Sequence[KnowledgeSource]) -> list[ProjectKnowledgeSourceRef]:
    refs = [
        ProjectKnowledgeSourceRef(
            label=f"Dream revalidated {source.source_kind} source",
            target=source.locator,
            kind=source.source_kind,
            digest=source.content_sha256,
        )
        for source in sources
    ]
    if not refs:
        raise ValueError("Dream knowledge write requires a current source")
    return refs


def _validate_writing_items(
    *,
    knowledge_items: Sequence[Mapping[str, Any]],
    canonical_title: str | None,
    canonical_statement: str | None,
    topic_path: Sequence[str],
    disposition: str,
) -> None:
    if knowledge_items and (canonical_title or canonical_statement or topic_path):
        raise ValueError("Dream writing decision mixes canonical output forms")
    items = list(knowledge_items)
    if not items:
        items = [
            {
                "title": canonical_title,
                "statement": canonical_statement,
                "topic_path": list(topic_path),
                "claim_kind": "procedure",
            }
        ]
    if not items:
        raise ValueError("Dream writing decision requires at least one knowledge item")
    for item in items:
        title = str(item.get("title") or "").strip()
        statement = str(item.get("statement") or "").strip()
        claim_kind = str(item.get("claim_kind") or "")
        if not title or not statement:
            raise ValueError("Dream writing decision requires title and statement")
        validate_atomic_knowledge_statement(statement)
        validate_knowledge_module_path(item.get("topic_path") or [])
        if claim_kind not in {
            "design_requirement",
            "implementation_fact",
            "durable_preference",
            "procedure",
        }:
            raise ValueError("Dream writing decision has an invalid claim kind")


def _required_terms(statement: str) -> list[str]:
    return sorted(
        {
            value.casefold()
            for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", statement)
            if value.casefold() not in {"and", "current", "from", "knowledge", "must", "not", "the", "this", "with"}
        }
    )


def _same_statement(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


__all__ = [
    "DreamAssimilationCandidate",
    "DreamPreparedAssimilation",
    "apply_dream_assimilation",
    "build_dream_maintenance_plan",
    "prepare_dream_assimilation",
    "validate_dream_assimilation_decision",
]
