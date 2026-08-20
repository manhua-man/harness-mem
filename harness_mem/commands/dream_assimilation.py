"""Trusted application of bounded Dream comparison decisions.

Dream works over already-governed current knowledge rather than over a
session-distill job.  This module gives that maintenance path the same
separation as ordinary assimilation: an untrusted provider proposes one
strictly bounded decision, then the runtime rechecks the real sources and
performs each reversible truth mutation itself.

The caller keeps reopened source text in memory.  It is present in the
provider manifest only for the immediate no-tool semantic call and is never
stored in a candidate, decision, Dream receipt, or current knowledge row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.commands.evidence_admission import validate_knowledge_sources
from harness_mem.commands.knowledge_assimilation import (
    assimilation_decision_id,
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


def validate_dream_assimilation_decision(
    prepared: DreamPreparedAssimilation,
    decision: AssimilationDecision,
) -> list[dict[str, Any]]:
    """Bind an untrusted provider decision to rechecked current knowledge.

    A Dream ``reject`` has deliberately narrower semantics than a session
    candidate rejection: it can retire *its own* contradicted row, or an exact
    duplicate whose equivalent survivor is named by the provider.  No other
    provider choice may remove current truth.
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
        if disposition not in {
            "confirm",
            "refine",
            "supersede",
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
        if disposition in {"confirm", "refine", "supersede"}:
            if handles != [own_handle]:
                raise ValueError(f"Dream {disposition} must target its own current truth")
        elif disposition == "reject":
            if len(handles) != 1:
                raise ValueError("Dream reject must name one current truth handle")
        elif handles:
            raise ValueError(f"Dream {disposition} must not target current truth")

        if disposition in {"refine", "supersede"}:
            _validate_writing_items(
                knowledge_items=knowledge_items,
                canonical_title=point.canonical_title,
                canonical_statement=point.canonical_statement,
                topic_path=point.topic_path,
                disposition=disposition,
            )
        elif knowledge_items or point.canonical_title or point.canonical_statement or point.topic_path:
            raise ValueError(f"Dream {disposition} cannot carry canonical knowledge")

        support = candidate.semantic_support
        durable = candidate.future_scope == "durable"
        if support == "supported" and durable:
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
                "canonical_title": point.canonical_title,
                "canonical_statement": point.canonical_statement,
                "topic_path": list(point.topic_path),
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
    """Recheck sources again, then commit each sanctioned Dream mutation.

    Each write is routed through the normal canonical truth mutation API and
    is undoable. Confirmation freshness is its existing dedicated canonical
    operation; it changes no statement and may advance a re-opened source
    digest only after the second byte-level check succeeds.
    """

    candidates = {candidate.candidate_id: candidate for candidate in prepared.candidates}
    if {str(point.get("candidate_id") or "") for point in plan} != set(candidates):
        raise ValueError("Dream assimilation plan is not bound to its candidates")
    store = backend.structured_store.knowledge_store
    outcomes: list[dict[str, Any]] = []
    for point in plan:
        candidate = candidates[str(point["candidate_id"])]
        validation = await validate_knowledge_sources(
            backend,
            project_name=prepared.project_name,
            sources=candidate.sources,
            project_root=prepared.project_root,
        )
        if validation.verification_outcome != "verified":
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "source_changed",
                    "reason": "Dream source changed before its truth transaction.",
                }
            )
            continue
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
        if disposition == "confirm":
            await store.refresh_entry_verification(
                project_name=prepared.project_name,
                entry_id=candidate.entry.id,
                verified_at=validation.verified_at or datetime.now().astimezone(),
                refresh_id=f"dream:{prepared.run_id}:{candidate.candidate_id}:confirm",
                refreshed_sources=candidate.sources,
            )
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
            mutation_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"harness-mem:dream-archive:{prepared.run_id}:{candidate.entry.id}",
                )
            )
            await store.archive_current_entry(
                project_name=prepared.project_name,
                entry_id=candidate.entry.id,
                mutation_id=mutation_id,
                reason=str(point["reason"]),
            )
            outcomes.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "entry_id": candidate.entry.id,
                    "status": "applied",
                    "truth_change": "retired",
                    "mutation_id": mutation_id,
                    "reason": str(point["reason"]),
                }
            )
            continue

        if disposition not in {"refine", "supersede"}:  # pragma: no cover - validator owns this.
            raise ValueError(f"unsupported Dream assimilation disposition: {disposition}")
        workspace_candidate = KnowledgeCandidate(
            id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"harness-mem:dream-candidate:{prepared.run_id}:{candidate.entry.id}",
                )
            ),
            project_name=prepared.project_name,
            candidate_type="memory",
            statement=candidate.entry.statement,
        )
        record_point = {
            **dict(point),
            "verified_at": validation.verified_at,
            "matched_truth_kinds": ["knowledge_entry"],
        }
        source_refs = _source_refs(candidate.sources)
        truth_ids = await record_assimilation_result(
            backend,
            candidate=workspace_candidate,
            point=record_point,
            project_root=prepared.project_root,
            source_refs=source_refs,
        )
        mutation_id = assimilation_decision_id(
            candidate_id=workspace_candidate.id,
            disposition=disposition,
            knowledge_ids=truth_ids,
            reason=str(point["reason"]),
        )
        await store.cleanup_candidate(workspace_candidate.id)
        outcomes.append(
            {
                "candidate_id": candidate.candidate_id,
                "entry_id": candidate.entry.id,
                "status": "applied",
                "truth_change": disposition,
                "truth_ids": truth_ids,
                "mutation_id": mutation_id,
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
    if disposition == "refine" and len(items) != 1:
        raise ValueError("Dream refine requires one replacement knowledge item")
    if disposition == "supersede" and not 1 <= len(items) <= 3:
        raise ValueError("Dream supersede requires one to three replacement knowledge items")
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
    "prepare_dream_assimilation",
    "validate_dream_assimilation_decision",
]
