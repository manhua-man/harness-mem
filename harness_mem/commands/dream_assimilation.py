"""Trusted application of bounded Dream comparison decisions.

Dream works over already-governed current knowledge rather than over a
session-distill job. Source classification can directly confirm or retire
qualified rows. Unresolved updates use the existing assimilation provider and
an independent final-output judgment before reaching this planner. The common
final-output, update-meaning and canonical commit owners authorize every write.
The retired private comparative validator has no runtime consumer.

The caller keeps reopened source text in memory.  It is present in the
provider manifest only for the immediate no-tool semantic call and is never
stored in a candidate, decision, Dream receipt, or current knowledge row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast, get_args
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.autonomous.models import (
    CandidateClaimUnit, CandidateVerificationDecision,
    CandidateVerificationPoint, OutputVerification, UpdateMeaningJudgment,
    DREAM_LITERAL_EDIT_CONTRACT, DREAM_LITERAL_RECHECK_CONTRACT, DURABLE_SOURCE_USES,
    DREAM_SOURCE_RECHECK_CONTRACT,
    verification_scope_status,
)
from harness_mem.commands.evidence_admission import (
    reopen_dream_knowledge_sources,
    validate_knowledge_sources,
)
from harness_mem.commands.knowledge_assimilation import (
    commit_shared_knowledge_change,
)
from harness_mem.commands.separated_assimilation import (
    prove_supplied_final_scope,
    target_version,
    validate_knowledge_module_path,
)
from harness_mem.core.schemas.source_report import (
    SourceReport,
    bind_report_split,
    source_report_snapshot,
)
from harness_mem.core.schemas import (
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeSource,
    ProjectKnowledgeSourceRef,
)
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement
from harness_mem.core.schemas.knowledge import ClaimKind
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
    verification_contract: str | None = None
    original_sources: tuple[KnowledgeSource, ...] | None = None


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


def _retained_report_text(point: CandidateVerificationPoint, *, allow_literal_edit: bool = False) -> str:
    units = _standalone_durable_units(point, body_start=0, allow_literal_edit=allow_literal_edit)
    if len(units) != 1:
        raise ValueError("Dream report refinement requires one complete verified account unit")
    return units[0][0]


def _standalone_durable_units(
    point: CandidateVerificationPoint, *, body_start: int, allow_literal_edit: bool = False,
) -> list[tuple[str, str, frozenset[int], CandidateClaimUnit]]:
    """Read explicit joint proofs, including exact v7 literal deletions."""
    segments = point.scope_segments
    starts: list[int] = []
    offset = 0
    for segment in segments:
        starts.append(offset)
        offset += len(segment.text)
    retained: list[tuple[str, str, frozenset[int], CandidateClaimUnit]] = []
    occupied: set[int] = set()
    for unit in point.claim_units:
        first, end = unit.first_segment, unit.end_segment_exclusive
        if not (0 <= first < end <= len(segments)):
            return []
        excluded = set(unit.excluded_segments)
        edited = bool(excluded or unit.title_start is not None or unit.title_end is not None)
        if edited and (not allow_literal_edit or point.literal_edit_contract != DREAM_LITERAL_EDIT_CONTRACT):
            return []
        if len(excluded) != len(unit.excluded_segments) or not excluded.issubset(range(first, end)):
            return []
        for index in excluded:
            part = segments[index]
            temporary = (part.source_support == "supported" and part.content_role == "temporary_context"
                and part.source_use == "task_context" and part.future_scope == "session_only")
            unsupported = (point.semantic_support == "partial"
                and part.source_support in {"unsupported", "contradicted"}
                and part.content_role in {"claim", "qualifier"})
            if not (temporary or unsupported):
                return []
        if not unit.selected_for_retention:
            continue
        if (unit.source_support != "supported" or not unit.standalone
                or unit.future_scope != "durable"
                or unit.source_use not in DURABLE_SOURCE_USES):
            return []
        if starts[first] < body_start:
            # The original title is checked separately and cannot become body.
            return []
        indexes = frozenset(index for index in range(first, end) if index not in excluded)
        selected = [segments[index] for index in sorted(indexes)]
        substantive = [part for part in selected if part.text.strip()]
        if (not substantive or not any(part.content_role == "claim" for part in substantive)
                or any(part.source_support != "supported"
                       or part.content_role not in {"claim", "qualifier"}
                       for part in substantive)):
            return []
        if occupied.intersection(indexes):
            return []
        occupied.update(indexes)
        text = "".join(part.text for part in selected).strip()
        # New edit authority is for the exact proposed output, not for the
        # original range or a runtime guess that its fragments fit together.
        if not text or (allow_literal_edit and unit.retained_text != text):
            return []
        retained.append((text, unit.source_use, indexes, unit))
    return sorted(retained, key=lambda row: min(row[2]))


@dataclass(frozen=True)
class DreamPreparedAssimilation:
    """A bounded project-local comparative assimilation manifest."""

    project_name: str
    project_root: Path
    run_id: str
    signal_kind: DreamSignalKind
    candidates: tuple[DreamAssimilationCandidate, ...]


def prepare_dream_assimilation(
    *,
    project_name: str,
    project_root: str | Path,
    run_id: str,
    signal_kind: DreamSignalKind,
    candidates: Sequence[DreamAssimilationCandidate],
) -> DreamPreparedAssimilation:
    """Bind one finite rechecked group to the common maintenance planner."""

    if not candidates:
        raise ValueError("Dream assimilation needs at least one verified candidate")
    root = Path(project_root).expanduser().resolve()
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Dream assimilation candidates must be unique")
    if any(candidate.entry.project_name != project_name for candidate in candidates):
        raise ValueError("Dream assimilation candidate crosses projects")

    return DreamPreparedAssimilation(
        project_name=project_name, project_root=root, run_id=run_id,
        signal_kind=signal_kind, candidates=tuple(candidates),
    )


def _entry_version_snapshot(entry: KnowledgeEntry) -> dict[str, Any]:
    snapshot = {
        "id": entry.id,
        "title": entry.title,
        "statement": entry.statement,
        "topic_path": list(entry.module_path),
        "source_report": source_report_snapshot(entry.source_report),
    }
    snapshot["version"] = target_version(snapshot)
    return snapshot


def _scope_decision_for_outputs(
    verifications: Sequence[OutputVerification | CandidateVerificationPoint],
    meaning: UpdateMeaningJudgment | None,
) -> CandidateVerificationDecision:
    points: list[CandidateVerificationPoint] = []
    for index, verdict in enumerate(verifications):
        if meaning is not None and (
            verdict.update_meaning_judgment is None
            or not verdict.update_meaning_judgment.agrees_with(meaning)
        ):
            raise ValueError("each final output must carry the same explicit whole-update judgment")
        if isinstance(verdict, CandidateVerificationPoint):
            points.append(verdict.model_copy(update={
                "candidate_index": index,
            }))
            continue
        points.append(CandidateVerificationPoint(
            candidate_index=index,
            semantic_support=verdict.semantic_support,
            future_scope=verdict.future_scope,
            source_use=verdict.source_use,
            reason=verdict.reason,
            scope_segments=list(verdict.scope_segments),
            update_meaning_judgment=verdict.update_meaning_judgment,
        ))
    return CandidateVerificationDecision(points=points)


def _meaning_for_replacement(
    entry: KnowledgeEntry,
    statements: Sequence[str],
    supplied: UpdateMeaningJudgment | None,
    predecessors: Sequence[KnowledgeEntry] = (),
) -> UpdateMeaningJudgment:
    snapshots = [_entry_version_snapshot(row) for row in predecessors or [entry]]
    if supplied is not None and supplied.covers(statements) and supplied.binds_predecessors(snapshots):
        return supplied
    raise ValueError("replacement has no accepted whole-update judgment for these exact predecessors and outputs")


def _report_split_maintenance_point(candidate: DreamAssimilationCandidate) -> dict[str, Any] | None:
    """One shared replace of a legacy report, or a no-write that keeps it."""

    point = candidate.scope_verification
    if point is None or not point.report_outputs:
        return None
    entry = candidate.entry
    refused = {
        "candidate_id": candidate.candidate_id,
        "entry_id": entry.id,
        "disposition": "no_write",
        "matched_truth_ids": [],
        "canonical_title": None,
        "canonical_statement": None,
        "topic_path": [],
        "knowledge_items": [],
        "reason": "Dream report split was not admitted.",
    }
    if point.literal_edit_contract is not None or candidate.verification_contract != DREAM_SOURCE_RECHECK_CONTRACT:
        refused["reason"] = "v7 literal proofs cannot authorize ordinary report admission."
        return refused
    report = entry.source_report
    revision = bool(point.report_preservation_inventory is not None
                    and point.report_preservation_inventory.get("mode") == "full_revision")
    mode = "source_backed_same_topic_revision" if revision else "literal_projection"
    if not isinstance(report, SourceReport) or (not revision and point.semantic_support != "supported"):
        refused["reason"] = "partial source support cannot be upgraded into independent reports"
        return refused
    try:
        for segment in (() if revision else point.scope_segments):
            if segment.content_role != "qualifier":
                continue
            must_remain = (
                segment.source_support != "supported"
                or segment.source_use in DURABLE_SOURCE_USES
            )
            if must_remain and not any(segment.text in output.text for output in point.report_outputs):
                raise ValueError("report split dropped an unsupported or independently useful qualifier")
        bound = bind_report_split(
            report,
            original_support=point.semantic_support,
            outputs=list(point.report_outputs),
            omissions=list(point.report_omissions),
            mode=mode,
        )
        if len(point.output_verifications) != len(bound):
            raise ValueError("Dream report split has no final title, body, and attribution verification.")
        items = [{
            "title": written.render_title(),
            "statement": written.render_statement(),
            "topic_path": list(entry.module_path),
            "claim_kind": "source_report",
            "source_report": source_report_snapshot(written),
        } for written in bound]
        meaning = _meaning_for_replacement(
            entry,
            [item["statement"] for item in items],
            point.update_meaning_judgment,
        )
        judgment = _scope_decision_for_outputs(point.output_verifications, meaning)
        payload = {
            "disposition": "replace",
            "candidate_id": candidate.candidate_id,
            "knowledge_items": items,
            "targets": [_entry_version_snapshot(entry)],
            "update_meaning_judgment": meaning.model_dump(mode="json"),
        }
        if point.report_preservation_inventory is not None:
            payload["report_preservation_inventory"] = point.report_preservation_inventory
        prove_supplied_final_scope(payload=payload, judgment=judgment)
    except ValueError as exc:
        refused["reason"] = str(exc)
        return refused
    return {
        "candidate_id": candidate.candidate_id,
        "entry_id": entry.id,
        "disposition": "replace",
        "matched_truth_ids": [entry.id],
        "canonical_title": None,
        "canonical_statement": None,
        "topic_path": [],
        "knowledge_items": [{
            "title": item["title"],
            "statement": item["statement"],
            "topic_path": item["topic_path"],
            "claim_kind": "source_report",
        } for item in items],
        "reason": point.reason,
        "report_split": {
            "mode": mode,
            "original_support": point.semantic_support,
            "outputs": [output.model_dump(mode="json") for output in point.report_outputs],
            "omissions": [omission.model_dump(mode="json") for omission in point.report_omissions],
        },
        "update_meaning_judgment": meaning.model_dump(mode="json"),
        "final_scope_judgment": judgment.model_dump(mode="json"),
        **({"report_preservation_inventory": point.report_preservation_inventory}
           if point.report_preservation_inventory is not None else {}),
    }


def _outputs_have_final_scope(
    candidate: DreamAssimilationCandidate, items: Sequence[Mapping[str, Any]],
    predecessors: Sequence[KnowledgeEntry] = (),
) -> bool:
    point = candidate.scope_verification
    if point is None or len(point.output_verifications) != len(items):
        return False
    try:
        meaning = _meaning_for_replacement(
            candidate.entry,
            [str(item["statement"]) for item in items],
            point.update_meaning_judgment,
            predecessors=predecessors,
        )
        payload = {
            "disposition": "refine",
            "candidate_id": candidate.candidate_id,
            "knowledge_items": [dict(item) for item in items],
            "targets": [_entry_version_snapshot(row) for row in predecessors or [candidate.entry]],
            "update_meaning_judgment": meaning.model_dump(mode="json"),
        }
        prove_supplied_final_scope(
            payload=payload,
            judgment=_scope_decision_for_outputs(point.output_verifications, meaning),
        )
    except ValueError:
        return False
    return True


def _confirmation_has_final_scope(candidate: DreamAssimilationCandidate) -> bool:
    point = candidate.scope_verification
    entry = candidate.entry
    if (point is None or candidate.semantic_support != "supported"
            or candidate.future_scope != "durable"
            or point.semantic_support != "supported"
            or point.future_scope != "durable"
            or point.source_use not in DURABLE_SOURCE_USES
            or point.literal_edit_contract is not None):
        return False
    target: dict[str, Any] = {"title": entry.title, "statement": entry.statement}
    if entry.source_report is not None:
        target["source_report"] = source_report_snapshot(entry.source_report)
    try:
        prove_supplied_final_scope(
            payload={
                "disposition": "confirm",
                "candidate_id": candidate.candidate_id,
                "knowledge_items": [],
                "targets": [target],
            },
            judgment=(_scope_decision_for_outputs(point.output_verifications, None)
                      if point.output_verifications else CandidateVerificationDecision(points=[
                          point.model_copy(update={"candidate_index": 0}),
                      ])),
        )
    except ValueError:
        return False
    return True


def _maintenance_shell(candidate: DreamAssimilationCandidate, reason: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "entry_id": candidate.entry.id,
        "disposition": "no_write",
        "matched_truth_ids": [],
        "canonical_title": None,
        "canonical_statement": None,
        "topic_path": [],
        "knowledge_items": [],
        "reason": reason,
    }


def build_dream_maintenance_plan(
    prepared: DreamPreparedAssimilation,
) -> list[dict[str, Any]]:
    """Derive a plan from source classification and independently checked outputs.

    Source reopening has already admitted every supplied candidate. Unclear
    or partial results without accepted final outputs remain unchanged; a supported durable row is
    refreshed, and an explicitly contradicted row may retire only itself.
    Only complete disposable content-role partitions may retire temporary rows.
    A complete mixed partition may retain verbatim, independently
    complete durable claims; it cannot manufacture rewritten knowledge.
    """

    plan: list[dict[str, Any]] = []
    entries_by_id = {candidate.entry.id: candidate.entry for candidate in prepared.candidates}
    for candidate in prepared.candidates:
        verification = candidate.scope_verification
        if verification is not None and verification.replacement_items:
            proposed = [item.model_dump(mode="json") for item in verification.replacement_items]
            target_ids = list(verification.replacement_target_ids or [candidate.entry.id])
            targets = [entries_by_id[identity] for identity in target_ids if identity in entries_by_id]
            if (candidate.entry.id not in target_ids or len(set(target_ids)) != len(target_ids)
                    or len(targets) != len(target_ids) or any(row.source_report is not None for row in targets)
                    or candidate.entry.source_report is not None
                    or any(item["claim_kind"] == "source_report" for item in proposed)
                    or not _outputs_have_final_scope(candidate, proposed, predecessors=targets)):
                plan.append(_maintenance_shell(candidate,
                    "Replacement outputs require complete final scope, authority and whole-update verification."))
                continue
            meaning = _meaning_for_replacement(candidate.entry,
                [str(item["statement"]) for item in proposed], verification.update_meaning_judgment,
                predecessors=targets)
            plan.append({
                **_maintenance_shell(candidate, verification.reason),
                "disposition": "replace" if len(targets) > 1 else "refine", "matched_truth_ids": target_ids,
                "knowledge_items": proposed,
                "update_meaning_judgment": meaning.model_dump(mode="json"),
                "final_scope_judgment": _scope_decision_for_outputs(
                    verification.output_verifications, meaning).model_dump(mode="json"),
            })
            continue
        split_point = _report_split_maintenance_point(candidate)
        if split_point is not None:
            plan.append(split_point)
            continue
        disposition = "no_write"
        target_ids: list[str] = []
        reason = candidate.verification_reason
        retained_items = _verified_durable_scope_items(candidate)
        if retained_items and not _outputs_have_final_scope(candidate, retained_items):
            plan.append(_maintenance_shell(
                candidate,
                "Literal refinement has no final verification of the written title and body.",
            ))
            continue
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
                    if _confirmation_has_final_scope(candidate):
                        disposition = "confirm"
                        target_ids = [candidate.entry.id]
                    else:
                        reason = (
                            "Dream final title and body verification did not establish complete durable support."
                            if candidate.scope_verification is not None
                            and candidate.scope_verification.output_verifications
                            else "Dream confirmation has no final title and body verification."
                        )
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
        record = {
            "candidate_id": candidate.candidate_id,
            "entry_id": candidate.entry.id,
            "disposition": disposition,
            "matched_truth_ids": target_ids,
            "canonical_title": None,
            "canonical_statement": None,
            "topic_path": [],
            "knowledge_items": retained_items,
            "reason": reason,
        }
        if disposition == "refine" and retained_items and candidate.scope_verification is not None:
            meaning = _meaning_for_replacement(
                candidate.entry,
                [str(item["statement"]) for item in retained_items],
                candidate.scope_verification.update_meaning_judgment,
            )
            judgment = _scope_decision_for_outputs(
                candidate.scope_verification.output_verifications, meaning,
            )
            record["update_meaning_judgment"] = meaning.model_dump(mode="json")
            record["final_scope_judgment"] = judgment.model_dump(mode="json")
        elif disposition == "confirm" and candidate.scope_verification is not None:
            original = candidate.scope_verification
            record["final_scope_judgment"] = (
                _scope_decision_for_outputs(original.output_verifications, None)
                if original.output_verifications else CandidateVerificationDecision(points=[
                    original.model_copy(update={"candidate_index": 0}),
                ])
            ).model_dump(mode="json")
        plan.append(record)
    # One multi-target point owns the whole replacement transaction. Overlapping
    # proposed replacements are ambiguous and remain unchanged. A target with
    # no competing proposal is accounted for by its successful owning point.
    owners: dict[str, list[str]] = {}
    for point in plan:
        if point["disposition"] in {"refine", "replace"}:
            meaning = point["update_meaning_judgment"]
            point["retained_conditions"] = list(meaning["predecessor_conditions"])
            point["undecided_state"] = meaning.get("undecided_state")
            for identity in point["matched_truth_ids"]:
                owners.setdefault(identity, []).append(point["candidate_id"])
    blocked = {owner for values in owners.values() if len(values) > 1 for owner in values}
    for index, point in enumerate(plan):
        candidate = next(row for row in prepared.candidates if row.candidate_id == point["candidate_id"])
        if candidate.candidate_id in blocked:
            plan[index] = _maintenance_shell(candidate, "Overlapping replacement proposals require review.")
            continue
        owner = next((owner for owner in owners.get(candidate.entry.id, [])
                      if owner != candidate.candidate_id and owner not in blocked), None)
        if owner is not None:
            plan[index] = {**_maintenance_shell(candidate, "This target belongs to one jointly verified replacement."),
                           "covered_by_candidate_id": owner}
    plan.sort(key=lambda point: bool(point.get("covered_by_candidate_id")))
    return plan


def _verified_durable_scope_items(candidate: DreamAssimilationCandidate) -> list[dict[str, Any]]:
    """Retain complete source-supported units from an existing mixed row.

    The original point may remain partial. No new extraction candidate becomes
    verified through this maintenance-only literal derivation.
    """
    point = candidate.scope_verification
    if (point is None
            or candidate.verification_contract not in {DREAM_LITERAL_RECHECK_CONTRACT, DREAM_SOURCE_RECHECK_CONTRACT}
            or candidate.semantic_support not in {"supported", "partial"}
            or point.semantic_support != candidate.semantic_support
            or not point.scope_segments
            or "".join(part.text for part in point.scope_segments) != dream_scope_text(candidate.entry)):
        return []
    body_start = len(candidate.entry.title) + 1 if candidate.entry.source_report is None else 0
    units = _standalone_durable_units(point, body_start=body_start, allow_literal_edit=True)
    if not units or (candidate.entry.source_report is not None and len(units) != 1):
        return []
    retained_indexes = frozenset(index for _text, _use, indexes, _unit in units for index in indexes)
    removed = False
    offset = 0
    prefix = []
    prefix_indexes = set()
    for index, segment in enumerate(point.scope_segments):
        end = offset + len(segment.text)
        if offset < body_start:
            if end > body_start:
                return []
            if segment.text.strip():
                prefix.append(segment)
                prefix_indexes.add(index)
            offset = end
            continue
        offset = end
        if index in retained_indexes or not segment.text.strip():
            continue
        # A claim-unit inventory cannot disagree with a disposable segment.
        # In particular, an uncertain or session-scoped constraint is not
        # silently discarded because it was also labelled temporary.
        if any(unit.first_segment <= index < unit.end_segment_exclusive
               and index not in unit.excluded_segments
               and unit.source_support not in {"unsupported", "contradicted"}
               for unit in point.claim_units):
            return []
        temporary = (segment.content_role == "temporary_context"
            and segment.source_support == "supported"
            and segment.source_use == "task_context" and segment.future_scope == "session_only")
        unsupported = (point.semantic_support == "partial"
            and segment.source_support in {"unsupported", "contradicted"}
            and segment.content_role in {"claim", "qualifier"}
            and (segment.standalone or any(index in unit.excluded_segments
                 for _text, _use, _indexes, unit in units)))
        if not temporary and not unsupported:
            # Unknown text and detached qualifiers stay in current knowledge.
            return []
        removed = True
    if candidate.entry.source_report is not None:
        if any(unit.title_start is not None or unit.title_end is not None
               for _text, _use, _indexes, unit in units):
            return []
        report = candidate.entry.source_report.model_copy(update={
            "text": _retained_report_text(point, allow_literal_edit=True),
        })
        items = [{
            "title": report.render_title(), "statement": report.render_statement(),
            "topic_path": list(candidate.entry.module_path), "claim_kind": "source_report",
        }]
    else:
        keep_title = bool(prefix) and all(part.content_role in {"claim", "qualifier"}
            and part.source_support == "supported" for part in prefix)
        replace_title = bool(prefix) and point.semantic_support == "partial" and all(
            part.content_role in {"claim", "qualifier"}
            and part.source_support in {"unsupported", "contradicted"} for part in prefix)
        if replace_title and any(
                unit.source_support not in {"unsupported", "contradicted"}
                and prefix_indexes.intersection(range(unit.first_segment, unit.end_segment_exclusive))
                for unit in point.claim_units):
            # A new heading cannot erase another substantive or unknown account
            # of the original title; no redundancy is inferred from wording.
            replace_title = False
        if not keep_title and not replace_title:
            return []
        items = []
        for text, source_use, _indexes, unit in units:
            if unit.title_and_text_support != "supported":
                return []
            if keep_title:
                if unit.title_start is not None or unit.title_end is not None:
                    return []
                title = candidate.entry.title
            else:
                title_start, title_end = unit.title_start, unit.title_end
                if (title_start is None or title_end is None or not 0 <= title_start < title_end <= len(text)
                        or point.literal_edit_contract != DREAM_LITERAL_EDIT_CONTRACT):
                    return []
                title = text[title_start:title_end].strip()
                if not title:
                    return []
                removed = True
            items.append({
                "title": title, "statement": text,
                "topic_path": list(candidate.entry.module_path),
                "claim_kind": "design_requirement" if source_use == "standing_decision" else "procedure",
            })
    if not removed:
        return []
    try:
        _validate_writing_items(knowledge_items=items, canonical_title=None,
                                canonical_statement=None, topic_path=[], disposition="refine")
    except ValueError:
        return []
    return items




async def _confirmation_source_rows(
    backend: LocalMemoryBackend, *, prepared: DreamPreparedAssimilation,
    candidate: DreamAssimilationCandidate,
) -> tuple[tuple[KnowledgeSource, ...], tuple[KnowledgeSource, ...]] | None:
    """Align semantic context to the original descriptors without rewriting identity.

    Expanded user context is independent proof. It is never a replacement
    locator for the stored source row. Repository content may advance only to
    the exact digest supplied to the independent semantic verification.
    """
    original = candidate.original_sources
    if original is None:
        # Compatibility for direct callers holding untransformed descriptors.
        # An expanded user ref cannot prove whether its persisted original was
        # a plain anchor or an already marked source; it needs the real snapshot.
        if any(source.source_kind == "user_statement" and
               {"context", "anchor_sha256"}.intersection(parse_qs(urlparse(source.locator).fragment))
               for source in candidate.sources):
            return None
        original = candidate.sources
    original_by_id = {source.id: source for source in original}
    proved_by_id = {source.id: source for source in candidate.sources}
    if (not original or len(original_by_id) != len(original)
            or len(proved_by_id) != len(candidate.sources)
            or set(original_by_id) != set(proved_by_id)
            or any(source.project_name != prepared.project_name or source.knowledge_id != candidate.entry.id
                   for source in (*original, *candidate.sources))):
        return None
    current = await backend.structured_store.knowledge_store.list_sources(candidate.entry.id)
    current_by_id = {source.id: source for source in current}
    if (len(current_by_id) != len(current) or set(current_by_id) != set(original_by_id)
            or any(current_by_id[identity].to_dict() != source.to_dict()
                   for identity, source in original_by_id.items())):
        return None
    validation, reopened, effective = await reopen_dream_knowledge_sources(
        backend, project_name=prepared.project_name, sources=original,
        project_root=prepared.project_root,
    )
    aligned = {source.id: source for source in effective}
    if (validation.verification_outcome != "verified"
            or len(reopened) != len(original) or len(aligned) != len(original)
            or any(not item.content or item.truncated for item in reopened)
            or set(aligned) != set(proved_by_id)
            or any(aligned[identity].to_dict() != source.to_dict()
                   for identity, source in proved_by_id.items())):
        return None
    refreshed = tuple(source.model_copy(update={
        "content_sha256": aligned[source.id].content_sha256,
    }) if source.source_kind == "repository" else source for source in original)
    return tuple(original), refreshed


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
        if str(point.get("disposition")) in {"confirm", "reject", "refine", "replace"} or point.get("covered_by_candidate_id"):
            expected = derived[str(point["candidate_id"])]
            if dict(point) != expected:
                raise ValueError("Dream mutation must exactly match its complete verified maintenance plan")
    store = backend.structured_store.knowledge_store
    outcomes: list[dict[str, Any]] = []
    for point in plan:
        candidate = candidates[str(point["candidate_id"])]
        disposition = str(point["disposition"])
        if disposition in {"no_write", "defer", "conflict"}:
            covered = point.get("covered_by_candidate_id")
            owner_succeeded = covered is not None and any(
                item["candidate_id"] == covered and item["status"] == "applied"
                for item in outcomes)
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "applied" if owner_succeeded else "rejected",
                    **({"truth_change": "covered_by_replacement"} if owner_succeeded else {}),
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
        predecessor_changed = any(
            current is None
            or current.statement != target.entry.statement
            or current.title != target.entry.title
            or current.module_path != target.entry.module_path
            or current.source_report != target.entry.source_report
            for target, current in zip(target_candidates, current_targets)
        )
        if predecessor_changed and disposition not in {"refine", "replace"}:
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
            aligned_sources = await _confirmation_source_rows(
                backend, prepared=prepared, candidate=candidate,
            )
            if aligned_sources is None:
                outcomes.append({
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "source_changed",
                    "reason": "Dream confirmation sources no longer match their original and semantic snapshots.",
                })
                continue
            original_sources, refreshed_sources = aligned_sources
            verified_at = validation.verified_at or datetime.now().astimezone()
            try:
                await commit_shared_knowledge_change(
                    backend,
                    candidate=KnowledgeCandidate(
                        project_name=prepared.project_name,
                        candidate_type="memory",
                        statement=candidate.entry.statement,
                        source_report=candidate.entry.source_report,
                    ),
                    point=point,
                    project_root=prepared.project_root,
                    source_refs=_source_refs(candidate.sources),
                    confirmation_refresh={
                        "project_name": prepared.project_name,
                        "entry_id": candidate.entry.id,
                        "verified_at": verified_at,
                        "refresh_id": f"dream:{prepared.run_id}:{candidate.candidate_id}:confirm",
                        "refreshed_sources": refreshed_sources,
                        "expected_sources": original_sources,
                        "expected_entry": current_targets[0],
                    },
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
                # Duplicate retirement names the survivor as context. The row
                # this candidate retires is still its own current entry.
                await commit_shared_knowledge_change(
                    backend,
                    candidate=KnowledgeCandidate(
                        project_name=prepared.project_name,
                        candidate_type="memory",
                        statement=candidate.entry.statement,
                        source_report=candidate.entry.source_report,
                    ),
                    point={**dict(point), "matched_truth_ids": [candidate.entry.id]},
                    expected_predecessor_entries=[
                        entry for entry in current_targets if entry is not None
                    ],
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
        workspace_statement = candidate.entry.statement
        if retained_report is not None and point.get("report_split"):
            # The split binds the original cited text, not a rendered wrapper.
            workspace_statement = retained_report.text
        elif retained_report is not None:
            retained_report = retained_report.model_copy(update={
                "text": _retained_report_text(cast(CandidateVerificationPoint, candidate.scope_verification),
                    allow_literal_edit=candidate.verification_contract in {
                        DREAM_LITERAL_RECHECK_CONTRACT, DREAM_SOURCE_RECHECK_CONTRACT}),
            })
            workspace_statement = retained_report.text
        workspace_candidate = KnowledgeCandidate(
            id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"harness-mem:dream-candidate:{prepared.run_id}:{candidate.entry.id}",
                )
            ),
            project_name=prepared.project_name,
            candidate_type="memory",
            statement=workspace_statement,
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
            committed = await commit_shared_knowledge_change(
                backend,
                candidate=workspace_candidate,
                point=record_point,
                project_root=prepared.project_root,
                source_refs=source_refs,
                expected_predecessor_entries=[target.entry for target in target_candidates],
            )
            truth_ids = committed["truth_ids"]
        except CanonicalTransactionPreconditionError:
            outcomes.append({
                "candidate_id": candidate.candidate_id, "entry_id": candidate.entry.id,
                "status": "source_changed", "reason": "Dream refinement target changed before commit.",
            })
            continue
        except ValueError as exc:
            outcomes.append({
                "candidate_id": candidate.candidate_id, "entry_id": candidate.entry.id,
                "status": "failed", "reason": str(exc),
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
        # Share the canonical writing kinds; a local pre-report whitelist used
        # to silently discard every otherwise valid literal report refinement.
        # Candidate authority and exact retained items are checked by the plan.
        if claim_kind not in get_args(ClaimKind):
            raise ValueError("Dream writing decision has an invalid claim kind")






__all__ = [
    "DreamAssimilationCandidate",
    "DreamPreparedAssimilation",
    "apply_dream_assimilation",
    "build_dream_maintenance_plan",
    "prepare_dream_assimilation",
]
