"""Bounded, post-verification preparation for memory assimilation.

This layer sits after evidence revalidation and before any candidate reaches
the truth layer.  It deliberately exposes opaque same-project truth handles
to the semantic provider and keeps raw transcript content out of the second
call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from harness_mem.commands.evidence_admission import (
    answer_gate_status,
    apply_validation,
    validate_candidate_evidence,
)
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RelationFact,
    RuleCandidate,
    SupersedeCandidate,
)
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.event_log import StateEventType, append_state_event
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_MAX_CURRENT_TRUTH = 12


@dataclass(frozen=True)
class PreparedAssimilation:
    """Validated inputs plus automatic non-writing outcomes for one job."""

    project_name: str
    candidate_ids: tuple[str, ...]
    eligible_candidate_ids: tuple[str, ...]
    automatic_points: tuple[dict[str, Any], ...]
    truth_by_handle: dict[str, dict[str, str]]
    manifest: dict[str, Any]


async def prepare_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidate_ids: Sequence[str],
) -> PreparedAssimilation:
    """Revalidate each point and prepare a transcript-free provider manifest."""

    candidates = await _load_candidates(backend, candidate_ids)
    for candidate in candidates:
        if candidate.project_name != project_name:
            raise ValueError("candidate belongs to another project")
        validation = await validate_candidate_evidence(backend, candidate)
        apply_validation(candidate, validation)
        await _save_candidate(backend, candidate)

    automatic: list[dict[str, Any]] = []
    eligible: list[Any] = []
    for candidate in candidates:
        status = answer_gate_status(candidate)
        if status == "ANSWERED":
            eligible.append(candidate)
            continue
        automatic.append(_automatic_point(candidate, answer_status=status))

    truth_by_handle, current_truth = await _current_truth_handles(
        backend,
        project_name=project_name,
        candidates=eligible,
    )
    manifest = {
        "contract_version": "memory-assimilation-v1",
        "project_name": project_name,
        "verified_candidates": [_candidate_projection(candidate) for candidate in eligible],
        "current_truth": current_truth,
    }
    return PreparedAssimilation(
        project_name=project_name,
        candidate_ids=tuple(str(item.id) for item in candidates),
        eligible_candidate_ids=tuple(str(item.id) for item in eligible),
        automatic_points=tuple(automatic),
        truth_by_handle=truth_by_handle,
        manifest=manifest,
    )


def validate_assimilation_decision(
    prepared: PreparedAssimilation,
    decision: Any,
) -> dict[str, Any]:
    """Validate complete point coverage and handle scope before persistence."""

    points = list(decision.points)
    ids = [point.candidate_id for point in points]
    expected = set(prepared.eligible_candidate_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("assimilation decision contains duplicate candidate ids")
    if set(ids) != expected:
        raise ValueError("assimilation decision must cover every verified candidate once")

    normalized: list[dict[str, Any]] = [dict(item) for item in prepared.automatic_points]
    for point in points:
        handles = list(point.matched_truth_handles)
        if len(handles) != len(set(handles)):
            raise ValueError("assimilation point contains duplicate truth handles")
        if any(handle not in prepared.truth_by_handle for handle in handles):
            raise ValueError("assimilation point references an unavailable truth handle")
        disposition = point.disposition
        if disposition == "add" and handles:
            raise ValueError("add must not target current truth")
        if disposition in {"confirm", "refine", "supersede"} and len(handles) != 1:
            raise ValueError(f"{disposition} requires exactly one current truth handle")
        if disposition == "conflict" and len(handles) > 1:
            raise ValueError("conflict may reference at most one current truth handle")
        if disposition in {"add", "refine", "supersede"} and (
            not str(point.canonical_title or "").strip()
            or not str(point.canonical_statement or "").strip()
        ):
            raise ValueError(f"{disposition} requires canonical title and statement")
        normalized.append(
            {
                "candidate_id": point.candidate_id,
                "answer_status": "ANSWERED",
                "disposition": disposition,
                "matched_truth_ids": [
                    prepared.truth_by_handle[handle]["id"] for handle in handles
                ],
                "matched_truth_kinds": [
                    prepared.truth_by_handle[handle]["kind"] for handle in handles
                ],
                "canonical_title": point.canonical_title,
                "canonical_statement": point.canonical_statement,
                "topic_path": list(point.topic_path),
                "reason": point.reason,
            }
        )
    normalized.sort(key=lambda item: prepared.candidate_ids.index(item["candidate_id"]))
    return {
        "version": "v1",
        "point_count": len(normalized),
        "points": normalized,
        "provider_candidate_ids": list(prepared.eligible_candidate_ids),
    }


async def apply_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidate_ids: Sequence[str],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a validated per-point plan without reopening session-wide gates.

    This function owns the new autonomous path only. Manual MCP governance
    remains untouched. Every candidate must receive exactly one terminal
    result; non-writing outcomes stay outside normal retrieval.
    """

    points = list(plan.get("points") or [])
    expected = [str(value) for value in candidate_ids]
    if len(points) != len(expected) or {str(item.get("candidate_id")) for item in points} != set(expected):
        raise ValueError("assimilation plan does not cover this job's candidates")
    if len({str(item.get("candidate_id")) for item in points}) != len(points):
        raise ValueError("assimilation plan has duplicate candidate results")

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
        candidate = await _load_one_candidate(backend, candidate_id)
        if candidate is None:
            counts["missing"] += 1
            continue
        if candidate.project_name != project_name:
            raise ValueError("assimilation candidate belongs to another project")
        result = await _apply_point(backend, candidate=candidate, point=point)
        results.append(result)
        disposition = str(result["disposition"])
        if disposition in {"add", "refine", "supersede"}:
            counts["promoted"] += 1
        elif disposition == "confirm":
            counts["confirmed"] += 1
        elif disposition == "no_write":
            counts["no_write"] += 1
        elif disposition == "handoff":
            counts["handoff"] += 1
        elif disposition == "conflict":
            counts["conflict"] += 1
        elif disposition == "defer":
            counts["deferred"] += 1
        else:
            counts["rejected"] += 1
    return {**counts, "points": results}


async def _apply_point(
    backend: LocalMemoryBackend,
    *,
    candidate: Any,
    point: Mapping[str, Any],
) -> dict[str, Any]:
    disposition = str(point.get("disposition") or "reject")
    candidate.assimilation_disposition = disposition
    candidate.assimilation_reason = str(point.get("reason") or "")
    candidate.canonical_title = point.get("canonical_title")
    candidate.topic_path = list(point.get("topic_path") or [])
    if isinstance(candidate, MemoryEntry) and point.get("canonical_statement"):
        candidate.content = str(point["canonical_statement"])
    await _save_candidate(backend, candidate)

    matched_truth_ids = [str(item) for item in point.get("matched_truth_ids") or []]
    matched_truth_kinds = [str(item) for item in point.get("matched_truth_kinds") or []]
    canonical_truth_ids: list[str] = []
    handoff_id: str | None = None
    final_status = "rejected"
    if disposition == "add":
        canonical_truth_ids = [await _materialize_add(backend, candidate)]
        final_status = "auto_confirmed"
    elif disposition in {"refine", "supersede"}:
        if len(matched_truth_ids) != 1 or len(matched_truth_kinds) != 1:
            raise ValueError(f"{disposition} is missing its current truth target")
        replacement_id = await _materialize_add(backend, candidate, activate=False)
        replacement_kind = _candidate_truth_kind(candidate)
        target_id = matched_truth_ids[0]
        target_kind = matched_truth_kinds[0]
        if replacement_kind != target_kind:
            raise ValueError(f"{disposition} target kind does not match replacement")
        supersede_id = str(
            uuid5(
                NAMESPACE_URL,
                f"harness-mem:assimilation:{disposition}:{candidate.id}:{target_id}",
            )
        )
        existing = await backend.structured_store.get_supersede_candidate(supersede_id)
        if existing is None:
            existing = SupersedeCandidate(
                id=supersede_id,
                project_name=candidate.project_name,
                target_type=target_kind,
                target_id=target_id,
                replacement_type=replacement_kind,
                replacement_id=replacement_id,
                reason=str(point.get("reason") or disposition),
                evidence=f"assimilation:{candidate.id}",
                source=candidate.id,
            )
            await backend.structured_store.save_supersede_candidate(existing)
        if existing.status == "pending":
            existing = await backend.structured_store.confirm_supersede_candidate(
                existing.id,
                reviewer_id="autonomous_assimilation",
            )
        if existing is None or existing.status != "user_confirmed":
            raise ValueError("atomic supersede could not be confirmed")
        canonical_truth_ids = [replacement_id]
        final_status = "auto_confirmed"
    elif disposition == "confirm":
        if len(matched_truth_ids) != 1:
            raise ValueError("confirm requires exactly one current truth target")
        canonical_truth_ids = matched_truth_ids
    elif disposition == "handoff":
        handoff_id = await _materialize_handoff(backend, candidate, point)
    elif disposition in {"defer", "conflict"}:
        final_status = "deferred"
    elif disposition not in {"no_write", "reject"}:
        raise ValueError(f"unknown assimilation disposition: {disposition}")

    if disposition not in {"add", "refine", "supersede"}:
        final_status = "deferred" if disposition in {"defer", "conflict"} else "rejected"
    update = _status_updater(backend, candidate)
    if not await update(candidate.id, final_status):
        raise ValueError(f"candidate status transition failed: {candidate.id} -> {final_status}")
    append_state_event(
        backend.data_dir,
        event_type=(
            StateEventType.TRUTH_CONFIRMED
            if final_status == "auto_confirmed"
            else StateEventType.CANDIDATE_REVIEWED
            if final_status == "deferred"
            else StateEventType.TRUTH_REJECTED
        ),
        project_name=candidate.project_name,
        target_kind=_candidate_kind(candidate),
        target_id=candidate.id,
        status=final_status,
        source_surface="autonomous_assimilation",
        actor="autonomous_assimilation",
        payload={
            "disposition": disposition,
            "canonical_truth_ids": canonical_truth_ids,
            "handoff_id": handoff_id,
        },
    )
    return {
        "candidate_id": candidate.id,
        "answer_status": answer_gate_status(candidate),
        "disposition": disposition,
        "canonical_truth_ids": canonical_truth_ids,
        "handoff_id": handoff_id,
    }


async def _materialize_add(
    backend: LocalMemoryBackend,
    candidate: Any,
    *,
    activate: bool = True,
) -> str:
    if isinstance(candidate, MemoryEntry):
        if activate:
            if not await backend.structured_store.update_memory_entry_status(
                candidate.id, "auto_confirmed"
            ):
                raise ValueError("memory candidate could not become current truth")
        return candidate.id
    if isinstance(candidate, RelationFact):
        if activate:
            if not await backend.structured_store.update_relation_fact_status(
                candidate.id, "auto_confirmed"
            ):
                raise ValueError("relation candidate could not become current truth")
        return candidate.id
    if isinstance(candidate, RuleCandidate):
        rule_id = str(uuid5(NAMESPACE_URL, f"harness-mem:assimilated-rule:{candidate.id}"))
        existing = await backend.structured_store.get_confirmed_rule(rule_id)
        if existing is None:
            rule = ConfirmedRule(
                id=rule_id,
                project_name=candidate.project_name,
                pattern=candidate.pattern,
                trigger=candidate.trigger,
                examples=list(candidate.examples),
                source_candidate_id=candidate.id,
                source_session_id=candidate.session_id,
                title=candidate.canonical_title,
                topic_path=list(candidate.topic_path),
                provenance={"distill_job_id": candidate.distill_job_id},
            )
            await backend.structured_store.save_confirmed_rule(rule)
        if activate:
            if not await backend.structured_store.update_rule_candidate_status(
                candidate.id, "auto_confirmed"
            ):
                raise ValueError("rule candidate could not become current truth")
        return rule_id
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


async def _materialize_handoff(
    backend: LocalMemoryBackend,
    candidate: Any,
    point: Mapping[str, Any],
) -> str:
    handoff_id = str(uuid5(NAMESPACE_URL, f"harness-mem:assimilation-handoff:{candidate.id}"))
    existing = await backend.structured_store.get_task_handoff(handoff_id)
    if existing is not None:
        return existing.id
    statement = str(point.get("canonical_statement") or _candidate_projection(candidate)["statement"])
    handoff = TaskHandoff(
        id=handoff_id,
        project_name=candidate.project_name,
        task_id=f"assimilation:{candidate.id}",
        summary=statement,
        status="in_progress",
        next_steps=[statement],
        context={"distill_job_id": candidate.distill_job_id, "candidate_id": candidate.id},
    )
    return await backend.structured_store.save_task_handoff(handoff)


async def _load_one_candidate(backend: LocalMemoryBackend, candidate_id: str) -> Any | None:
    candidate: Any | None = await backend.structured_store.get_memory_entry(candidate_id)
    if candidate is None:
        candidate = await backend.structured_store.get_rule_candidate(candidate_id)
    if candidate is None:
        candidate = await backend.structured_store.get_relation_fact(candidate_id)
    return candidate


def _status_updater(backend: LocalMemoryBackend, candidate: Any) -> Any:
    if isinstance(candidate, MemoryEntry):
        return backend.structured_store.update_memory_entry_status
    if isinstance(candidate, RuleCandidate):
        return backend.structured_store.update_rule_candidate_status
    if isinstance(candidate, RelationFact):
        return backend.structured_store.update_relation_fact_status
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _candidate_kind(candidate: Any) -> str:
    if isinstance(candidate, MemoryEntry):
        return "memory_entry"
    if isinstance(candidate, RuleCandidate):
        return "rule_candidate"
    if isinstance(candidate, RelationFact):
        return "relation_fact"
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _candidate_truth_kind(candidate: Any) -> str:
    if isinstance(candidate, MemoryEntry):
        return "memory_entry"
    if isinstance(candidate, RuleCandidate):
        return "confirmed_rule"
    if isinstance(candidate, RelationFact):
        return "relation_fact"
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


async def _load_candidates(
    backend: LocalMemoryBackend,
    candidate_ids: Sequence[str],
) -> list[Any]:
    candidates: list[Any] = []
    for candidate_id in candidate_ids:
        candidate: Any | None = await backend.structured_store.get_memory_entry(
            str(candidate_id)
        )
        if candidate is None:
            candidate = await backend.structured_store.get_rule_candidate(str(candidate_id))
        if candidate is None:
            candidate = await backend.structured_store.get_relation_fact(str(candidate_id))
        if candidate is None:
            raise ValueError(f"candidate is missing: {candidate_id}")
        candidates.append(candidate)
    return candidates


async def _save_candidate(backend: LocalMemoryBackend, candidate: Any) -> None:
    if isinstance(candidate, MemoryEntry):
        await backend.structured_store.save_memory_entry(candidate)
    elif isinstance(candidate, RuleCandidate):
        await backend.structured_store.save_rule_candidate(candidate)
    elif isinstance(candidate, RelationFact):
        await backend.structured_store.save_relation_fact(candidate)
    else:  # pragma: no cover - callers only load the three supported kinds.
        raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _automatic_point(candidate: Any, *, answer_status: str) -> dict[str, Any]:
    if answer_status in {"CONTRADICTED", "STALE"}:
        disposition = "reject"
    elif answer_status == "NOT_APPLICABLE":
        disposition = "no_write"
    else:
        disposition = "defer"
    return {
        "candidate_id": str(candidate.id),
        "answer_status": answer_status,
        "disposition": disposition,
        "matched_truth_ids": [],
        "matched_truth_kinds": [],
        "canonical_title": None,
        "canonical_statement": None,
        "topic_path": [],
        "reason": f"runtime evidence gate is {answer_status}",
    }


def _candidate_projection(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, MemoryEntry):
        statement = candidate.content
        kind = "memory_entry"
    elif isinstance(candidate, RuleCandidate):
        statement = f"When {candidate.trigger}, {candidate.pattern}".strip()
        kind = "rule"
    elif isinstance(candidate, RelationFact):
        statement = f"{candidate.source_entity} {candidate.relation_type} {candidate.target_entity}"
        kind = "relation_fact"
    else:  # pragma: no cover
        raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")
    return {
        "candidate_id": str(candidate.id),
        "kind": kind,
        "statement": statement,
        "evidence_basis": candidate.evidence_basis,
        "answer_status": answer_gate_status(candidate),
    }


async def _current_truth_handles(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidates: Sequence[Any],
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    memories = await backend.structured_store.list_memory_entries(
        project_name, limit=100
    )
    relations = await backend.structured_store.list_relation_facts(
        project_name, limit=100
    )
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    source: list[tuple[str, str, str, str]] = []
    for memory in memories:
        source.append(
            (
                "memory_entry",
                memory.id,
                memory.canonical_title or memory.category,
                memory.content,
            )
        )
    for relation in relations:
        source.append(
            (
                "relation_fact",
                relation.id,
                relation.canonical_title or relation.relation_type,
                f"{relation.source_entity} {relation.relation_type} {relation.target_entity}",
            )
        )
    for rule in rules:
        source.append(("confirmed_rule", rule.id, rule.trigger, rule.pattern))
    candidate_terms = {
        token.lower()
        for candidate in candidates
        for token in _candidate_projection(candidate)["statement"].split()
        if len(token) >= 4
    }
    source.sort(
        key=lambda item: (
            -sum(token.lower().strip(".,:;()") in candidate_terms for token in item[3].split()),
            item[0],
            item[1],
        )
    )
    by_handle: dict[str, dict[str, str]] = {}
    projected: list[dict[str, str]] = []
    for index, (kind, truth_id, title, statement) in enumerate(source[:_MAX_CURRENT_TRUTH], 1):
        handle = f"T{index}"
        by_handle[handle] = {"id": truth_id, "kind": kind}
        projected.append(
            {
                "handle": handle,
                "kind": kind,
                "title": str(title),
                "statement": str(statement),
            }
        )
    return by_handle, projected


__all__ = [
    "PreparedAssimilation",
    "apply_assimilation",
    "prepare_assimilation",
    "validate_assimilation_decision",
]
