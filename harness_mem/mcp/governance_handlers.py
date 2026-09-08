"""Candidate, current-knowledge decision, and handoff MCP handlers.

This module owns governance write implementations.  It reaches the main MCP
runtime only through three narrow compatibility callbacks so backend binding,
audit events, and stable distill candidate IDs retain one owner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from harness_mem.core.schemas import EvidenceRef
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.event_log import StateEventType


def _get_backend():
    from harness_mem.mcp import tool_handlers as core

    return core._get_backend()


def _record_state_event(*args, **kwargs):
    from harness_mem.mcp import tool_handlers as core

    return core._record_state_event(*args, **kwargs)


def _distill_candidate_id(*args, **kwargs):
    from harness_mem.mcp import tool_handlers as core

    return core._distill_candidate_id(*args, **kwargs)


def _evidence_fields(
    *,
    distill_job_id: str | None,
    evidence_basis: str | None,
    verification_outcome: str | None,
    verification_refs: list[dict[str, Any]] | None,
    verification_reason_codes: list[str] | None,
) -> dict[str, Any]:
    """Normalize a v0.9.5 evidence envelope without accepting verified time."""

    basis = evidence_basis
    outcome = verification_outcome
    reasons = list(verification_reason_codes or [])
    if basis is None or outcome is None:
        basis = basis or "transcript"
        outcome = "unverified"
        reasons.append("evidence_envelope_missing")
    return {
        "evidence_basis": basis,
        "verification_outcome": outcome,
        "verification_refs": [
            EvidenceRef.from_dict(item) for item in verification_refs or []
        ],
        "verification_reason_codes": list(dict.fromkeys(reasons)),
    }


def _assimilation_fields(
    *,
    assimilation_disposition: str | None,
    assimilation_reason: str | None,
    assimilation_target_ids: list[str] | None,
    canonical_title: str | None,
    topic_path: list[str] | None,
) -> dict[str, Any]:
    """Carry the post-verification proposal without treating it as truth."""

    return {
        "assimilation_disposition": assimilation_disposition,
        "assimilation_reason": assimilation_reason,
        "assimilation_target_ids": list(assimilation_target_ids or []),
        "canonical_title": canonical_title,
        "topic_path": list(topic_path or []),
    }


def _suggest_separated_candidate(
    backend: Any,
    *,
    kind: str,
    candidate_id: str,
    project_name: str,
    statement: str,
    distill_job_id: str | None,
    evidence_fields: dict[str, Any],
    assimilation_fields: dict[str, Any],
) -> tuple[Any, bool, str | None]:
    """Persist a public suggestion without creating a legacy truth-like row."""

    from harness_mem.commands.separated_assimilation import (
        admit_separated_candidate,
    )

    candidate, replay = asyncio.run(
        admit_separated_candidate(
            backend,
            candidate_id=candidate_id,
            project_name=project_name,
            candidate_type=kind,
            statement=statement,
            distill_job_id=distill_job_id,
            **evidence_fields,
            **assimilation_fields,
        )
    )
    state_event_id = None
    if not replay:
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.CANDIDATE_CREATED,
            project_name=project_name,
            target_kind="knowledge_candidate",
            target_id=candidate.id,
            status="pending",
            source_surface="mcp.govern_memory",
            payload={
                "candidate_type": kind,
                "evidence_basis": evidence_fields["evidence_basis"],
                "verification_outcome": evidence_fields["verification_outcome"],
            },
        )
    return candidate, replay, state_event_id


def tool_suggest_rule(
    project_name: str,
    pattern: str,
    trigger: str,
    session_id: str | None = None,
    examples: list[str] | None = None,
    distill_job_id: str | None = None,
    evidence_basis: str | None = None,
    verification_outcome: str | None = None,
    verification_refs: list[dict[str, Any]] | None = None,
    verification_reason_codes: list[str] | None = None,
    assimilation_disposition: str | None = None,
    assimilation_reason: str | None = None,
    assimilation_target_ids: list[str] | None = None,
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a rule as job-scoped processing material."""
    backend = _get_backend()
    payload = {
        "pattern": pattern,
        "trigger": trigger,
        "examples": examples or [],
    }
    candidate_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="rule",
        payload=payload,
    ) or str(uuid4())
    evidence_fields = _evidence_fields(
        distill_job_id=distill_job_id,
        evidence_basis=evidence_basis,
        verification_outcome=verification_outcome,
        verification_refs=verification_refs,
        verification_reason_codes=verification_reason_codes,
    )
    assimilation_fields = _assimilation_fields(
        assimilation_disposition=assimilation_disposition,
        assimilation_reason=assimilation_reason,
        assimilation_target_ids=assimilation_target_ids,
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    candidate, replay, state_event_id = _suggest_separated_candidate(
        backend,
        kind="rule",
        candidate_id=candidate_id,
        project_name=project_name,
        distill_job_id=distill_job_id,
        statement=f"When {str(trigger).strip()}, {str(pattern).strip()}".strip(),
        evidence_fields=evidence_fields,
        assimilation_fields=assimilation_fields,
    )
    result = {
        "success": True,
        "candidate_id": candidate.id,
        "pattern": pattern,
        "trigger": trigger,
        "status": "suggested",
        "state_event_id": state_event_id,
    }
    if replay:
        result["idempotent_replay"] = True
    return result


def tool_suggest_memory_entry(
    project_name: str,
    category: str,
    content: str,
    source: str,
    confidence: float = 0.7,
    tags: list[str] | None = None,
    distill_job_id: str | None = None,
    evidence_basis: str | None = None,
    verification_outcome: str | None = None,
    verification_refs: list[dict[str, Any]] | None = None,
    verification_reason_codes: list[str] | None = None,
    assimilation_disposition: str | None = None,
    assimilation_reason: str | None = None,
    assimilation_target_ids: list[str] | None = None,
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a memory point as job-scoped processing material."""
    backend = _get_backend()
    payload = {
        "category": category,
        "content": content,
        "source": source,
        "tags": tags or [],
    }
    entry_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="memory",
        payload=payload,
    ) or str(uuid4())
    evidence_fields = _evidence_fields(
        distill_job_id=distill_job_id,
        evidence_basis=evidence_basis,
        verification_outcome=verification_outcome,
        verification_refs=verification_refs,
        verification_reason_codes=verification_reason_codes,
    )
    assimilation_fields = _assimilation_fields(
        assimilation_disposition=assimilation_disposition,
        assimilation_reason=assimilation_reason,
        assimilation_target_ids=assimilation_target_ids,
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    candidate, replay, state_event_id = _suggest_separated_candidate(
        backend,
        kind="memory",
        candidate_id=entry_id,
        project_name=project_name,
        distill_job_id=distill_job_id,
        statement=content,
        evidence_fields=evidence_fields,
        assimilation_fields=assimilation_fields,
    )
    result = {
        "success": True,
        "entry_id": candidate.id,
        "category": category,
        "status": "pending",
        "state_event_id": state_event_id,
    }
    if replay:
        result["idempotent_replay"] = True
    return result


def tool_suggest_relation_fact(
    project_name: str,
    source_entity: str,
    target_entity: str,
    relation_type: str,
    evidence: str,
    source: str,
    confidence: float = 0.7,
    distill_job_id: str | None = None,
    evidence_basis: str | None = None,
    verification_outcome: str | None = None,
    verification_refs: list[dict[str, Any]] | None = None,
    verification_reason_codes: list[str] | None = None,
    assimilation_disposition: str | None = None,
    assimilation_reason: str | None = None,
    assimilation_target_ids: list[str] | None = None,
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a relation as job-scoped processing material."""
    backend = _get_backend()
    payload = {
        "source_entity": source_entity,
        "target_entity": target_entity,
        "relation_type": relation_type,
        "evidence": evidence,
        "source": source,
    }
    fact_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="relation",
        payload=payload,
    ) or str(uuid4())
    evidence_fields = _evidence_fields(
        distill_job_id=distill_job_id,
        evidence_basis=evidence_basis,
        verification_outcome=verification_outcome,
        verification_refs=verification_refs,
        verification_reason_codes=verification_reason_codes,
    )
    assimilation_fields = _assimilation_fields(
        assimilation_disposition=assimilation_disposition,
        assimilation_reason=assimilation_reason,
        assimilation_target_ids=assimilation_target_ids,
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    candidate, replay, state_event_id = _suggest_separated_candidate(
        backend,
        kind="relation",
        candidate_id=fact_id,
        project_name=project_name,
        distill_job_id=distill_job_id,
        statement=f"{source_entity} {relation_type} {target_entity}".strip(),
        evidence_fields=evidence_fields,
        assimilation_fields=assimilation_fields,
    )
    result = {
        "success": True,
        "fact_id": candidate.id,
        "relation": f"{source_entity} --{relation_type}--> {target_entity}",
        "status": "pending",
        "state_event_id": state_event_id,
    }
    if replay:
        result["idempotent_replay"] = True
    return result


def tool_create_task_handoff(
    project_name: str,
    task_id: str,
    summary: str,
    status: str,
    next_steps: list[str] | None = None,
    blockers: list[str] | None = None,
    distill_job_id: str | None = None,
) -> dict:
    """Create a task handoff to record progress."""
    from harness_mem.core.schemas.task_handoff import TaskHandoff

    backend = _get_backend()
    handoff_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="handoff",
        payload={
            "task_id": task_id,
            "summary": summary,
            "status": status,
            "next_steps": next_steps or [],
            "blockers": blockers or [],
        },
    )
    handoff = TaskHandoff(
        id=handoff_id or str(uuid4()),
        project_name=project_name,
        task_id=task_id,
        summary=summary,
        status=status,
        next_steps=next_steps or [],
        blockers=blockers or [],
        context={"distill_job_id": distill_job_id} if distill_job_id else {},
    )
    saved_id = asyncio.run(backend.structured_store.save_task_handoff(handoff))
    return {
        "success": True,
        "handoff_id": saved_id,
        "task_id": handoff.task_id,
        "distill_job_id": distill_job_id,
    }


def tool_govern_memory(action: str, arguments: dict[str, Any]) -> dict:
    """Composite candidate/truth write boundary exposed through MCP."""

    args = dict(arguments or {})
    try:
        if action == "suggest":
            kind = str(args.pop("kind", ""))
            suggest_handlers: dict[str, Callable[..., dict[str, Any]]] = {
                "memory": tool_suggest_memory_entry,
                "rule": tool_suggest_rule,
                "relation": tool_suggest_relation_fact,
            }
            handler = suggest_handlers.get(kind)
            if handler is None:
                return {
                    "success": False,
                    "error": "suggest kind must be memory, rule, or relation",
                }
            result = handler(**args)
        elif action == "decide":
            kind = str(args.pop("kind", ""))
            decision = str(args.pop("decision", ""))
            candidate_id_supplied = "candidate_id" in args
            candidate_id = str(args.pop("candidate_id", ""))
            reason = args.pop("reason", None)
            if kind == "knowledge":
                project_name = str(args.pop("project_name", "")).strip()
                if not project_name:
                    return {
                        "success": False,
                        "error": "knowledge decide requires project_name",
                    }
                if decision == "delete":
                    target_knowledge_ids = args.pop("target_knowledge_ids", None)
                    if (
                        candidate_id_supplied
                        or args
                        or not isinstance(target_knowledge_ids, list)
                        or len(target_knowledge_ids) != 1
                        or not str(target_knowledge_ids[0]).strip()
                    ):
                        return {
                            "success": False,
                            "error": (
                                "knowledge delete requires project_name and exactly one "
                                "target_knowledge_ids value; candidate_id, "
                                "knowledge_items, and extra arguments are not allowed"
                            ),
                        }
                    from harness_mem.commands.knowledge_assimilation import (
                        delete_current_knowledge,
                    )

                    result = asyncio.run(
                        delete_current_knowledge(
                            _get_backend(),
                            project_name=project_name,
                            target_knowledge_ids=target_knowledge_ids,
                        )
                    )
                    return {"governance_action": action, "success": True, **result}
                disposition = str(
                    args.pop(
                        "disposition", "add" if decision == "confirm" else "reject"
                    )
                )
                knowledge_items = list(args.pop("knowledge_items", []) or [])
                target_knowledge_ids = list(args.pop("target_knowledge_ids", []) or [])
                if (
                    args
                    or decision not in {"confirm", "reject"}
                    or not candidate_id
                    or disposition
                    not in {
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
                ):
                    return {
                        "success": False,
                        "error": (
                            "knowledge decide requires confirm|reject, candidate_id, and "
                            "optional disposition, knowledge_items, and target_knowledge_ids"
                        ),
                    }
                from harness_mem.commands.knowledge_assimilation import (
                    resolve_separated_review,
                )

                result = asyncio.run(
                    resolve_separated_review(
                        _get_backend(),
                        candidate_id=candidate_id,
                        disposition=cast(AssimilationDisposition, disposition),
                        reason=str(reason or f"review {decision}"),
                        knowledge_items=knowledge_items,
                        target_knowledge_ids=target_knowledge_ids,
                        expected_project_name=project_name,
                    )
                )
                state_event_id = _record_state_event(
                    _get_backend(),
                    event_type=StateEventType.CANDIDATE_REVIEWED,
                    project_name=project_name,
                    target_kind="knowledge_candidate",
                    target_id=candidate_id,
                    status=disposition,
                    source_surface="mcp.govern_memory",
                    payload={"disposition": disposition},
                )
                return {
                    "governance_action": action,
                    "success": True,
                    **result,
                    "state_event_id": state_event_id,
                }
            return {
                "success": False,
                "error": "decide requires kind=knowledge",
            }
        elif action == "handoff":
            result = tool_create_task_handoff(**args)
        else:
            return {"success": False, "error": "unknown governance action"}
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"invalid {action} arguments: {exc}"}
    return {"governance_action": action, **result}
