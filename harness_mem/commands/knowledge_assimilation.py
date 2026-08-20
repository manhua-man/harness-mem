"""Bridge autonomous assimilation into the separated knowledge repositories.

The compatibility candidate is retained until the read-path cutover, but it is
no longer the only record of a new durable conclusion.  This module creates the
new candidate, evidence, decision, and current-knowledge records without
putting audit fields on the knowledge row.
"""

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
    KnowledgeCandidateType,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.commands.evidence_admission import (
    validate_candidate_evidence,
    validate_knowledge_sources,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def mirror_candidate_and_evidence(
    backend: LocalMemoryBackend,
    candidate: Any,
) -> KnowledgeCandidate:
    """Persist the new candidate/evidence pair for one compatibility candidate."""

    store = backend.structured_store.knowledge_store
    separated = KnowledgeCandidate(
        id=str(candidate.id),
        project_name=candidate.project_name,
        candidate_type=_candidate_type(candidate),
        statement=_candidate_statement(candidate),
        status=_candidate_status(candidate),
        created_at=candidate.created_at,
        updated_at=getattr(candidate, "updated_at", candidate.created_at),
    )
    await store.save_candidate(separated)
    evidence = KnowledgeEvidence(
        id=str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge-evidence:{candidate.id}")),
        project_name=candidate.project_name,
        candidate_id=separated.id,
        distill_job_id=getattr(candidate, "distill_job_id", None),
        evidence_basis=getattr(candidate, "evidence_basis", None) or "transcript",
        verification_outcome=(
            getattr(candidate, "verification_outcome", None) or "unverified"
        ),
        verification_refs=list(getattr(candidate, "verification_refs", []) or []),
        verification_reason_codes=list(
            getattr(candidate, "verification_reason_codes", []) or []
        ),
        verified_at=getattr(candidate, "verified_at", None),
    )
    await store.save_evidence(evidence)
    return separated


async def record_assimilation_result(
    backend: LocalMemoryBackend,
    *,
    candidate: Any,
    point: Mapping[str, Any],
    project_root: str | Path | None = None,
    source_refs: Sequence[ProjectKnowledgeSourceRef] = (),
) -> list[str]:
    """Write clean entries and one append-only decision for a point outcome."""

    store = backend.structured_store.knowledge_store
    # New autonomous distillation creates a ``KnowledgeCandidate`` directly.
    # Its evidence was admitted before the second semantic call, so mirroring
    # it through a legacy MemoryEntry would reintroduce the very double-write
    # boundary this module owns.  Older/manual surfaces still arrive as one of
    # the compatibility candidate schemas and retain the bridge below.
    if isinstance(candidate, KnowledgeCandidate):
        separated = candidate
    else:
        separated = await mirror_candidate_and_evidence(backend, candidate)
    candidate_before = separated.model_copy(deep=True)
    disposition = _disposition(point)
    if disposition in {"add", "refine", "supersede", "confirm"} and (
        project_root is None or not source_refs
    ):
        resolved_root, resolved_refs, resolved_verified_at = (
            await resolve_candidate_source_context(
                backend,
                candidate=separated,
                evidence_items=await store.list_evidence(separated.id),
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
    if disposition in {"add", "refine", "supersede"}:
        for _index, item in enumerate(_knowledge_items(candidate, point), 1):
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
        if disposition in {"refine", "supersede"}:
            missing_target_ids: list[str] = []
            for target_id in matched_truth_ids:
                target = await store.get_entry(
                    target_id,
                    project_name=candidate.project_name,
                    project_root=project_root,
                )
                if target is None:
                    # The legacy compatibility path still applies its own
                    # supersede transition to a legacy truth type.  It may
                    # mirror the replacement into current knowledge, but must
                    # not pretend that the legacy target is a current
                    # ``knowledge_entries`` row or copy it into this ledger.
                    if isinstance(candidate, KnowledgeCandidate):
                        missing_target_ids.append(target_id)
                    continue
                predecessor_truth_ids.append(target.id)
                predecessor_entries.append(target)
            if missing_target_ids:
                decision_id = assimilation_decision_id(
                    candidate_id=candidate.id,
                    disposition=disposition,
                    knowledge_ids=knowledge_ids,
                    reason=str(point.get("reason", "")),
                )
                if await _is_committed_replacement_replay(
                    store,
                    decision_id=decision_id,
                    project_name=candidate.project_name,
                    disposition=disposition,
                    new_entries=new_entries,
                    predecessor_truth_ids=matched_truth_ids,
                ):
                    separated.status = _separated_status(disposition)
                    await store.save_candidate(separated)
                    return knowledge_ids
                raise ValueError(
                    "assimilation replacement target is not current knowledge"
                )
            if any(
                entry.id in predecessor_truth_ids for entry in new_entries
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

    separated.status = _separated_status(disposition)
    separated.updated_at = getattr(candidate, "updated_at", candidate.created_at)
    decision = AssimilationDecision(
        id=assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            reason=str(point.get("reason", "")),
        ),
        project_name=candidate.project_name,
        candidate_id=separated.id,
        disposition=disposition,
        canonical_truth_ids=knowledge_ids,
        predecessor_truth_ids=predecessor_truth_ids,
        predecessor_entries=predecessor_entries,
        reason=str(point.get("reason") or disposition),
    )
    if new_entries:
        await store.apply_truth_mutation(
            project_root=_required_project_root(project_root),
            candidate_before=candidate_before,
            candidate_after=separated,
            decision=decision,
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
            source_refs_by_entry={
                entry.id: list(source_refs) for entry in new_entries
            },
        )
        # The SQLite truth transaction is the commit point.  Persisting a
        # terminal workspace status before it succeeds would make a retry skip
        # a candidate whose durable knowledge was never written.
        await store.save_candidate(separated)
    else:
        await store.save_candidate(separated)
        await store.save_decision(decision, project_root=project_root)
    return knowledge_ids


def assimilation_decision_id(
    *,
    candidate_id: str,
    disposition: str,
    knowledge_ids: Sequence[str],
    reason: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "harness-mem:assimilation-decision:"
            f"{candidate_id}:{disposition}:{','.join(knowledge_ids)}:{reason}",
        )
    )


async def _is_committed_replacement_replay(
    store: Any,
    *,
    decision_id: str,
    project_name: str,
    disposition: str,
    new_entries: Sequence[KnowledgeEntry],
    predecessor_truth_ids: Sequence[str],
) -> bool:
    mutation = await store.get_mutation(decision_id)
    if mutation is None or (
        mutation.project_name != project_name
        or mutation.disposition != disposition
        or mutation.current_knowledge_ids != [entry.id for entry in new_entries]
    ):
        return False
    versions = [
        await store.get_version(version_id)
        for version_id in mutation.predecessor_version_ids
    ]
    if {item.knowledge_id for item in versions if item is not None} != set(
        predecessor_truth_ids
    ):
        return False
    for expected in new_entries:
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
        raise ValueError("knowledge mutation requires an explicit project root")
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
    candidate_before = candidate.model_copy(deep=True)
    evidence_items = await store.list_evidence(candidate.id)

    items = [dict(item) for item in knowledge_items]
    writes_truth = disposition in {"add", "refine", "supersede"}
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
    if disposition in {"refine", "supersede"} and len(target_knowledge_ids) != 1:
        raise ValueError(f"{disposition} requires exactly one current knowledge target")
    if disposition == "confirm" and len(target_knowledge_ids) != 1:
        raise ValueError("confirm requires exactly one current knowledge target")

    # Resolve every existing-truth dependency before creating a replacement.
    # Otherwise an invalid target would leave an orphan current entry behind
    # even though no assimilation decision can validly own it.
    target: KnowledgeEntry | None = None
    if disposition in {"refine", "supersede", "confirm"}:
        assert resolved_root is not None
        target = await store.get_entry(
            str(target_knowledge_ids[0]),
            project_name=candidate.project_name,
            project_root=resolved_root,
        )
        if target is None or target.project_name != candidate.project_name:
            raise ValueError("review target is not current project knowledge")
        target_validation = await validate_knowledge_sources(
            backend,
            project_name=candidate.project_name,
            sources=await store.list_sources(target.id),
            project_root=resolved_root,
        )
        if target_validation.verification_outcome != "verified":
            reasons = ", ".join(target_validation.reason_codes)
            raise ValueError(
                "review target source is no longer current: " + reasons
            )

    truth_ids: list[str] = []
    predecessor_truth_ids: list[str] = []
    predecessor_entries: list[KnowledgeEntry] = []
    new_entries: list[KnowledgeEntry] = []
    if writes_truth:
        if disposition == "refine" and len(items) != 1:
            raise ValueError("refine requires exactly one replacement item")
        if disposition == "supersede" and not 1 <= len(items) <= 3:
            raise ValueError("supersede requires one to three replacement items")
        for index, item in enumerate(items, 1):
            entry = _review_entry(
                candidate,
                item,
                index,
                source_refs=source_refs,
                verified_at=verified_at,
            )
            new_entries.append(entry)
            truth_ids.append(entry.id)
        if disposition in {"refine", "supersede"}:
            if target is None:  # Defensive: preflight above is required.
                raise AssertionError("review replacement target was not preflighted")
            predecessor_truth_ids = [target.id]
            predecessor_entries = [target]
            if any(
                entry.project_name == target.project_name
                and entry.module_path == target.module_path
                and entry.title == target.title
                and entry.statement == target.statement
                for entry in new_entries
            ):
                raise ValueError(
                    f"{disposition} replacement is identical to current knowledge; "
                    "use confirm"
                )
    elif disposition == "confirm":
        if target is None:  # Defensive: preflight above is required.
            raise AssertionError("review confirmation target was not preflighted")
        truth_ids = [target.id]

    candidate.status = _separated_status(disposition)
    decision = AssimilationDecision(
        id=str(
            uuid5(
                NAMESPACE_URL,
                "harness-mem:review-decision:"
                f"{candidate.id}:{disposition}:{','.join(truth_ids)}:{reason}",
            )
        ),
        project_name=candidate.project_name,
        candidate_id=candidate.id,
        disposition=disposition,
        canonical_truth_ids=truth_ids,
        predecessor_truth_ids=predecessor_truth_ids,
        predecessor_entries=predecessor_entries,
        reason=reason,
    )
    if new_entries:
        assert resolved_root is not None
        await store.apply_truth_mutation(
            project_root=resolved_root,
            candidate_before=candidate_before,
            candidate_after=candidate,
            decision=decision,
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
            source_refs_by_entry={
                entry.id: list(source_refs) for entry in new_entries
            },
        )
        await store.save_candidate(candidate)
    else:
        await store.save_candidate(candidate)
        await store.save_decision(decision, project_root=resolved_root)
    return {
        "candidate_id": candidate.id,
        "disposition": disposition,
        "canonical_truth_ids": truth_ids,
        "mutation_id": decision.id if new_entries else None,
    }


async def undo_separated_review(
    backend: LocalMemoryBackend,
    *,
    decision_id: str,
    reason: str,
    project_root: str | Path | None = None,
    expected_project_name: str | None = None,
) -> dict[str, Any]:
    """Reverse a Review change using its audit snapshot, not historical truth.

    Current truth is intentionally the only knowledge held in canonical
    SQLite.  The original decision carries the replaced-entry snapshot needed
    to restore it; entries created by that decision are removed from current
    truth and remain described only by the audit record.
    """

    del project_root
    store = backend.structured_store.knowledge_store
    original = await store.get_decision(decision_id)
    if original is None:
        raise ValueError("knowledge review decision is missing")
    if expected_project_name and original.project_name != expected_project_name:
        raise ValueError("knowledge review decision belongs to another project")
    reversal_id = str(
        uuid5(
            NAMESPACE_URL,
            f"harness-mem:review-undo:{decision_id}:{reason}",
        )
    )
    outcome = await store.undo_truth_mutation(
        mutation_id=decision_id,
        reversal_id=reversal_id,
    )
    return {
        "decision_id": decision_id,
        "reversal_decision_id": reversal_id,
        "restored_truth_ids": outcome["restored_knowledge_ids"],
        "retired_truth_ids": outcome["retired_knowledge_ids"],
    }


def _knowledge_items(candidate: Any, point: Mapping[str, Any]) -> list[dict[str, Any]]:
    supplied = list(point.get("knowledge_items") or [])
    if supplied:
        return [
            {
                "title": str(item["title"]).strip(),
                "statement": str(item["statement"]).strip(),
                "topic_path": [str(part).strip() for part in item["topic_path"]],
                "claim_kind": str(item["claim_kind"]),
            }
            for item in supplied
        ]

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
            "claim_kind": str(point.get("claim_kind") or _infer_claim_kind(candidate)),
        }
    ]


def _review_entry(
    candidate: KnowledgeCandidate,
    item: Mapping[str, Any],
    _index: int,
    *,
    source_refs: Sequence[ProjectKnowledgeSourceRef],
    verified_at: Any,
) -> KnowledgeEntry:
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
    identity = "\0".join(
        [candidate.project_name, *topic_path, title, statement]
    )
    return KnowledgeEntry(
        id=str(
            uuid5(
                NAMESPACE_URL,
                f"harness-mem:knowledge:{identity}",
            )
        ),
        project_name=candidate.project_name,
        title=title,
        statement=statement,
        module_path=topic_path,
        verified_at=verified_at,
    )


def _candidate_statement(candidate: Any) -> str:
    if isinstance(candidate, MemoryEntry):
        return candidate.content
    if isinstance(candidate, RuleCandidate):
        return f"When {candidate.trigger}, {candidate.pattern}".strip()
    if isinstance(candidate, RelationFact):
        return f"{candidate.source_entity} {candidate.relation_type} {candidate.target_entity}"
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _candidate_type(candidate: Any) -> KnowledgeCandidateType:
    if isinstance(candidate, MemoryEntry):
        return "memory"
    if isinstance(candidate, RuleCandidate):
        return "rule"
    if isinstance(candidate, RelationFact):
        return "relation"
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _candidate_status(candidate: Any) -> KnowledgeCandidateStatus:
    status = str(getattr(candidate, "status", "pending"))
    if status in {"pending", "deferred", "rejected"}:
        return cast(KnowledgeCandidateStatus, status)
    return "assimilated"


def _separated_status(disposition: AssimilationDisposition) -> KnowledgeCandidateStatus:
    if disposition == "defer":
        return "deferred"
    if disposition == "conflict":
        return "conflict"
    if disposition == "reject":
        return "rejected"
    return "assimilated"


def _infer_claim_kind(candidate: Any) -> str:
    if isinstance(candidate, KnowledgeCandidate):
        if candidate.candidate_type == "rule":
            return "procedure"
        return "procedure"
    if isinstance(candidate, RuleCandidate):
        return "procedure"
    if isinstance(candidate, MemoryEntry):
        if candidate.category in {"architecture", "decision"}:
            return "design_requirement"
        if candidate.evidence_basis == "repository":
            return "implementation_fact"
        if candidate.evidence_basis == "user_statement":
            return "durable_preference"
    return "procedure"


def _disposition(point: Mapping[str, Any]) -> AssimilationDisposition:
    value = str(point.get("disposition") or "reject")
    allowed = {
        "add",
        "refine",
        "confirm",
        "supersede",
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
    "mirror_candidate_and_evidence",
    "record_assimilation_result",
    "resolve_candidate_source_context",
    "resolve_separated_review",
    "undo_separated_review",
]
