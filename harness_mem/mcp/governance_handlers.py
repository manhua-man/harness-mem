"""Candidate, truth-decision, supersede, and handoff MCP handlers.

This module owns governance write implementations.  It reaches the main MCP
runtime only through three narrow compatibility callbacks so backend binding,
audit events, and stable distill candidate IDs retain one owner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from harness_mem.core.schemas import EvidenceRef, SupersedeCandidate
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.event_log import StateEventType
from harness_mem.retrieval_signals import record_retrieval_signal


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


def _apply_evidence_fields(candidate: Any, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        setattr(candidate, key, value)


def _assimilation_fields(
    *,
    assimilation_disposition: str | None,
    assimilation_reason: str | None,
    canonical_title: str | None,
    topic_path: list[str] | None,
) -> dict[str, Any]:
    """Carry the post-verification proposal without treating it as truth."""

    return {
        "assimilation_disposition": assimilation_disposition,
        "assimilation_reason": assimilation_reason,
        "canonical_title": canonical_title,
        "topic_path": list(topic_path or []),
    }


def _apply_assimilation_fields(candidate: Any, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        setattr(candidate, key, value)


def _revalidate_legacy_candidate(
    backend: Any,
    *,
    candidate: Any,
    kind: str,
) -> str:
    """Run the Answer Gate before a compatibility candidate can become truth."""

    from harness_mem.commands.evidence_admission import (
        answer_gate_status,
        apply_validation,
        validate_candidate_evidence,
    )

    validation = asyncio.run(validate_candidate_evidence(backend, candidate))
    apply_validation(candidate, validation)
    if kind == "memory":
        asyncio.run(backend.structured_store.save_memory_entry(candidate))
    elif kind == "rule":
        asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    elif kind == "relation":
        asyncio.run(backend.structured_store.save_relation_fact(candidate))
    else:  # pragma: no cover - internal callers constrain this union.
        raise ValueError(f"unsupported legacy candidate kind: {kind}")
    return answer_gate_status(candidate)


def _mirror_separated_suggestion(
    backend: Any,
    *,
    kind: str,
    result: dict[str, Any],
) -> None:
    """Keep the 0.9.x compatibility candidate out of the new audit boundary."""

    if not result.get("success"):
        return
    candidate_id = str(result.get("entry_id") or result.get("candidate_id") or "")
    if not candidate_id:
        raise ValueError("suggestion succeeded without a candidate id")
    if kind == "memory":
        candidate = asyncio.run(backend.structured_store.get_memory_entry(candidate_id))
    elif kind == "rule":
        candidate = asyncio.run(
            backend.structured_store.get_rule_candidate(candidate_id)
        )
    else:
        candidate = asyncio.run(
            backend.structured_store.get_relation_fact(candidate_id)
        )
    if candidate is None:
        raise ValueError("suggestion succeeded without a readable candidate")
    # MCP callers may propose an evidence envelope, but cannot promote their
    # own assertion that it is verified.  Re-run the trusted admission gate
    # before this compatibility row is mirrored into the separated review
    # boundary.  A manual suggestion without a job-bound source therefore
    # remains unverified and cannot be decided as current knowledge.
    _revalidate_legacy_candidate(backend, candidate=candidate, kind=kind)
    from harness_mem.commands.knowledge_assimilation import (
        mirror_candidate_and_evidence,
    )

    asyncio.run(mirror_candidate_and_evidence(backend, candidate))


def tool_create_rule_candidate(
    project_name: str,
    session_id: str,
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
) -> dict:
    """Create a rule candidate from a correction."""
    from uuid import uuid4
    from harness_mem.core.schemas import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id,
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.6,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="rule_candidate",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.create_rule_candidate",
        payload={"trigger": candidate.trigger, "session_id": candidate.session_id},
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "state_event_id": state_event_id,
    }


def tool_confirm_rule(rule_id: str) -> dict:
    """Promote a rule candidate to a confirmed rule."""
    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    from harness_mem.governance_status import (
        TRUTH_LAYER_STATUSES,
        user_confirm_status,
    )

    if candidate.status in TRUTH_LAYER_STATUSES:
        return {"success": False, "error": f"Candidate already confirmed: {rule_id}"}

    confirmed = ConfirmedRule(
        id=str(uuid4()),
        project_name=candidate.project_name,
        pattern=candidate.pattern,
        trigger=candidate.trigger,
        examples=candidate.examples,
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=candidate.id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(confirmed))
    asyncio.run(
        backend.structured_store.update_rule_candidate_status(
            rule_id, user_confirm_status()
        )
    )
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=candidate.project_name,
        target_kind="confirmed_rule",
        target_id=confirmed.id,
        status=user_confirm_status(),
        source_surface="mcp.confirm_rule",
        payload={"source_candidate_id": rule_id, "trigger": confirmed.trigger},
    )

    return {
        "success": True,
        "confirmed_rule_id": confirmed.id,
        "pattern": confirmed.pattern,
        "trigger": confirmed.trigger,
        "state_event_id": state_event_id,
    }


def tool_reject_rule(rule_id: str, reason: str | None = None) -> dict:
    """Reject a rule candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    from harness_mem.governance_status import TRUTH_LAYER_STATUSES

    if candidate.status in TRUTH_LAYER_STATUSES or candidate.status == "rejected":
        return {"success": False, "error": f"Candidate already processed: {rule_id}"}

    asyncio.run(
        backend.structured_store.update_rule_candidate_status(rule_id, "rejected")
    )
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_REJECTED,
        project_name=candidate.project_name,
        target_kind="rule_candidate",
        target_id=rule_id,
        status="rejected",
        source_surface="mcp.reject_rule",
        payload={"reason": reason or "No reason provided"},
    )
    return {
        "success": True,
        "rejected_rule_id": rule_id,
        "reason": reason or "No reason provided",
        "state_event_id": state_event_id,
    }


def tool_suggest_supersede(
    project_name: str,
    target_type: str,
    target_id: str,
    replacement_type: str,
    replacement_id: str,
    reason: str,
    evidence: str,
    source: str = "",
    confidence: float = 0.7,
) -> dict:
    backend = _get_backend()
    candidate = SupersedeCandidate(
        project_name=project_name,
        target_type=target_type,
        target_id=target_id,
        replacement_type=replacement_type,
        replacement_id=replacement_id,
        reason=reason,
        evidence=evidence,
        source=source,
        confidence=confidence,
    )
    saved_id = asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="supersede",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_supersede",
        payload={
            "target_type": target_type,
            "target_id": target_id,
            "replacement_type": replacement_type,
            "replacement_id": replacement_id,
        },
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "target_type": candidate.target_type,
        "target_id": candidate.target_id,
        "replacement_type": candidate.replacement_type,
        "replacement_id": candidate.replacement_id,
        "state_event_id": state_event_id,
    }


def tool_confirm_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    confirmed = asyncio.run(
        backend.structured_store.confirm_supersede_candidate(candidate_id)
    )
    if confirmed is None:
        return {
            "success": False,
            "error": f"Candidate not found or not pending: {candidate_id}",
        }
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.SUPERSEDE_COMPLETED,
        project_name=confirmed.project_name,
        target_kind="supersede",
        target_id=confirmed.id,
        status=confirmed.status,
        source_surface="mcp.confirm_supersede",
        payload={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
        },
    )
    return {
        "success": True,
        "candidate_id": confirmed.id,
        "status": confirmed.status,
        "state_event_id": state_event_id,
    }


def tool_reject_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_supersede_candidate(candidate_id)
    )
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {candidate_id}"}
    updated = asyncio.run(
        backend.structured_store.update_supersede_candidate_status(
            candidate_id, "rejected"
        )
    )
    if not updated:
        return {
            "success": False,
            "error": f"Failed to reject candidate: {candidate_id}",
        }
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_REJECTED,
        project_name=candidate.project_name,
        target_kind="supersede",
        target_id=candidate_id,
        status="rejected",
        source_surface="mcp.reject_supersede",
        payload={
            "target_type": candidate.target_type,
            "target_id": candidate.target_id,
            "replacement_type": candidate.replacement_type,
            "replacement_id": candidate.replacement_id,
        },
    )
    return {
        "success": True,
        "rejected_candidate_id": candidate_id,
        "status": "rejected",
        "state_event_id": state_event_id,
    }


def tool_suggest_correction(
    project_name: str,
    supersedes_rule_id: str,
    pattern: str,
    trigger: str,
    reason: str,
    *,
    examples: list[str] | None = None,
    source_session_id: str = "",
) -> dict:
    """One-shot rule replacement: create new rule + mark old rule historical.

    This is the right tool to call when reality changed (Tauri v1 -> v2,
    framework upgrade, policy reversal) and an old confirmed rule is now
    actively wrong. The caller has already named the specific old rule, so
    no extra human confirm step is needed — the supersede chain is applied
    immediately.

    For brand-new rules (no specific old rule to replace), use
    ``create_rule_candidate`` -> ``confirm_rule`` instead.
    """
    from harness_mem.governance_status import user_confirm_status

    backend = _get_backend()
    old_rule = asyncio.run(
        backend.structured_store.get_confirmed_rule(supersedes_rule_id)
    )
    if old_rule is None:
        return {
            "success": False,
            "error": f"ConfirmedRule not found: {supersedes_rule_id}",
        }
    if old_rule.project_name != project_name:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} belongs to project "
                f"{old_rule.project_name!r}, not {project_name!r}"
            ),
        }
    if old_rule.valid_to is not None:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} is already historical "
                f"(valid_to={old_rule.valid_to.isoformat()})"
            ),
        }

    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    source_id = source_session_id or "agent-correction"
    new_rule = ConfirmedRule(
        id=str(uuid4()),
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        examples=list(examples or []),
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=f"correction:{source_id}",
        source_session_id=source_id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(new_rule))

    candidate = SupersedeCandidate(
        id=str(uuid4()),
        project_name=project_name,
        target_type="confirmed_rule",
        target_id=old_rule.id,
        replacement_type="confirmed_rule",
        replacement_id=new_rule.id,
        reason=reason,
        evidence=f"Agent-driven correction (source: {source_id}).",
        source=f"correction:{source_id}",
        confidence=1.0,
    )
    asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    confirmed = asyncio.run(
        backend.structured_store.confirm_supersede_candidate(candidate.id)
    )
    if confirmed is None:
        return {
            "success": False,
            "error": (
                f"Saved new rule {new_rule.id} but supersede confirmation failed; "
                f"old rule {old_rule.id} is still current. "
                f"Call confirm_supersede with candidate_id={candidate.id} to retry."
            ),
            "new_rule_id": new_rule.id,
            "supersede_candidate_id": candidate.id,
        }
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
    truth_state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=project_name,
        target_kind="confirmed_rule",
        target_id=new_rule.id,
        status=user_confirm_status(),
        source_surface="mcp.suggest_correction",
        payload={"supersedes_rule_id": old_rule.id, "trigger": new_rule.trigger},
    )
    supersede_state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.SUPERSEDE_COMPLETED,
        project_name=project_name,
        target_kind="supersede",
        target_id=confirmed.id,
        status=confirmed.status,
        source_surface="mcp.suggest_correction",
        payload={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
        },
    )
    return {
        "success": True,
        "new_rule_id": new_rule.id,
        "old_rule_id": old_rule.id,
        "supersede_candidate_id": candidate.id,
        "old_rule_valid_to": confirmed.reviewed_at.isoformat()
        if confirmed.reviewed_at
        else None,
        "state_event_ids": [
            event_id
            for event_id in (truth_state_event_id, supersede_state_event_id)
            if event_id
        ],
    }


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
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a rule candidate for later review (lighter than confirm_rule)."""
    from harness_mem.core.schemas.rule_candidate import RuleCandidate

    backend = _get_backend()
    candidate_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="rule",
        payload={
            "pattern": pattern,
            "trigger": trigger,
            "examples": examples or [],
        },
    )
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
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    if candidate_id is not None:
        existing = asyncio.run(
            backend.structured_store.get_rule_candidate(candidate_id)
        )
        if existing is not None:
            _apply_evidence_fields(existing, evidence_fields)
            _apply_assimilation_fields(existing, assimilation_fields)
            asyncio.run(backend.structured_store.save_rule_candidate(existing))
            return {
                "success": True,
                "candidate_id": existing.id,
                "pattern": existing.pattern,
                "trigger": existing.trigger,
                "status": "suggested",
                "idempotent_replay": True,
                "state_event_id": None,
            }
    job = (
        backend.transcript_store.get_distill_job(distill_job_id)
        if distill_job_id
        else None
    )
    candidate = RuleCandidate(
        id=candidate_id or str(uuid4()),
        project_name=project_name,
        session_id=session_id or (job.session_id if job is not None else ""),
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.5,
        status="pending",
        distill_job_id=distill_job_id,
        **evidence_fields,
        **assimilation_fields,
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="rule_candidate",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_rule",
        payload={
            "trigger": candidate.trigger,
            "evidence_basis": candidate.evidence_basis,
            "verification_outcome": candidate.verification_outcome,
        },
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "status": "suggested",
        "state_event_id": state_event_id,
    }


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
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a memory entry for later review."""
    from harness_mem.core.schemas.memory_entry import MemoryEntry

    backend = _get_backend()
    entry_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="memory",
        payload={
            "category": category,
            "content": content,
            "source": source,
            "tags": tags or [],
        },
    )
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
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    if entry_id is not None:
        existing = asyncio.run(backend.structured_store.get_memory_entry(entry_id))
        if existing is not None:
            _apply_evidence_fields(existing, evidence_fields)
            _apply_assimilation_fields(existing, assimilation_fields)
            asyncio.run(backend.structured_store.save_memory_entry(existing))
            return {
                "success": True,
                "entry_id": existing.id,
                "category": existing.category,
                "status": existing.status,
                "idempotent_replay": True,
                "state_event_id": None,
            }
    entry = MemoryEntry(
        id=entry_id or str(uuid4()),
        project_name=project_name,
        category=category,
        content=content,
        source=source,
        confidence=confidence,
        status="pending",
        tags=tags or [],
        distill_job_id=distill_job_id,
        **evidence_fields,
        **assimilation_fields,
    )
    saved_id = asyncio.run(backend.structured_store.save_memory_entry(entry))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="memory_entry",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_memory_entry",
        payload={
            "category": entry.category,
            "source": entry.source,
            "evidence_basis": entry.evidence_basis,
            "verification_outcome": entry.verification_outcome,
        },
    )
    return {
        "success": True,
        "entry_id": saved_id,
        "category": entry.category,
        "status": "pending",
        "state_event_id": state_event_id,
    }


def tool_confirm_memory_entry(entry_id: str) -> dict:
    """Confirm a pending memory entry."""
    backend = _get_backend()
    from harness_mem.governance_status import user_confirm_status

    success = asyncio.run(
        backend.structured_store.update_memory_entry_status(
            entry_id, user_confirm_status()
        )
    )
    state_event_id = None
    if success:
        entry = asyncio.run(backend.structured_store.get_memory_entry(entry_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_CONFIRMED,
            project_name=entry.project_name if entry else None,
            target_kind="memory_entry",
            target_id=entry_id,
            status=user_confirm_status(),
            source_surface="mcp.confirm_memory_entry",
            payload={"category": getattr(entry, "category", None)},
        )
    return {
        "success": success,
        "entry_id": entry_id,
        "status": user_confirm_status() if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_reject_memory_entry(entry_id: str) -> dict:
    """Reject a pending memory entry."""
    backend = _get_backend()
    success = asyncio.run(
        backend.structured_store.update_memory_entry_status(entry_id, "rejected")
    )
    state_event_id = None
    if success:
        entry = asyncio.run(backend.structured_store.get_memory_entry(entry_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=entry.project_name if entry else None,
            target_kind="memory_entry",
            target_id=entry_id,
            status="rejected",
            source_surface="mcp.reject_memory_entry",
            payload={"category": getattr(entry, "category", None)},
        )
    return {
        "success": success,
        "entry_id": entry_id,
        "status": "rejected" if success else "not_found",
        "state_event_id": state_event_id,
    }


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
    canonical_title: str | None = None,
    topic_path: list[str] | None = None,
) -> dict:
    """Suggest a relation fact for later review."""
    from harness_mem.core.schemas.relation_fact import RelationFact

    backend = _get_backend()
    fact_id = _distill_candidate_id(
        backend,
        project_name=project_name,
        distill_job_id=distill_job_id,
        candidate_kind="relation",
        payload={
            "source_entity": source_entity,
            "target_entity": target_entity,
            "relation_type": relation_type,
            "evidence": evidence,
            "source": source,
        },
    )
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
        canonical_title=canonical_title,
        topic_path=topic_path,
    )
    if fact_id is not None:
        existing = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
        if existing is not None:
            _apply_evidence_fields(existing, evidence_fields)
            _apply_assimilation_fields(existing, assimilation_fields)
            asyncio.run(backend.structured_store.save_relation_fact(existing))
            return {
                "success": True,
                "fact_id": existing.id,
                "relation": (
                    f"{existing.source_entity} --{existing.relation_type}--> "
                    f"{existing.target_entity}"
                ),
                "status": existing.status,
                "idempotent_replay": True,
                "state_event_id": None,
            }
    fact = RelationFact(
        id=fact_id or str(uuid4()),
        project_name=project_name,
        source_entity=source_entity,
        target_entity=target_entity,
        relation_type=relation_type,
        evidence=evidence,
        source=source,
        confidence=confidence,
        status="pending",
        distill_job_id=distill_job_id,
        **evidence_fields,
        **assimilation_fields,
    )
    saved_id = asyncio.run(backend.structured_store.save_relation_fact(fact))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="relation_fact",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_relation_fact",
        payload={
            "source_entity": source_entity,
            "target_entity": target_entity,
            "relation_type": relation_type,
            "evidence_basis": fact.evidence_basis,
            "verification_outcome": fact.verification_outcome,
        },
    )
    return {
        "success": True,
        "fact_id": saved_id,
        "relation": f"{source_entity} --{relation_type}--> {target_entity}",
        "status": "pending",
        "state_event_id": state_event_id,
    }


def tool_confirm_relation_fact(fact_id: str) -> dict:
    """Confirm a pending relation fact."""
    from harness_mem.governance_status import user_confirm_status

    backend = _get_backend()
    success = asyncio.run(
        backend.structured_store.update_relation_fact_status(
            fact_id, user_confirm_status()
        )
    )
    state_event_id = None
    if success:
        fact = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_CONFIRMED,
            project_name=fact.project_name if fact else None,
            target_kind="relation_fact",
            target_id=fact_id,
            status=user_confirm_status(),
            source_surface="mcp.confirm_relation_fact",
            payload={"relation_type": getattr(fact, "relation_type", None)},
        )
    return {
        "success": success,
        "fact_id": fact_id,
        "status": user_confirm_status() if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_reject_relation_fact(fact_id: str) -> dict:
    """Reject a pending relation fact."""
    backend = _get_backend()
    success = asyncio.run(
        backend.structured_store.update_relation_fact_status(fact_id, "rejected")
    )
    state_event_id = None
    if success:
        fact = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=fact.project_name if fact else None,
            target_kind="relation_fact",
            target_id=fact_id,
            status="rejected",
            source_surface="mcp.reject_relation_fact",
            payload={"relation_type": getattr(fact, "relation_type", None)},
        )
    return {
        "success": success,
        "fact_id": fact_id,
        "status": "rejected" if success else "not_found",
        "state_event_id": state_event_id,
    }


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
            _mirror_separated_suggestion(_get_backend(), kind=kind, result=result)
        elif action == "decide":
            kind = str(args.pop("kind", ""))
            decision = str(args.pop("decision", ""))
            candidate_id = str(args.pop("candidate_id", ""))
            reason = args.pop("reason", None)
            if kind == "knowledge":
                project_name = str(args.pop("project_name", "")).strip()
                if not project_name:
                    return {
                        "success": False,
                        "error": "knowledge decide requires project_name",
                    }
                if decision == "undo":
                    decision_id = str(args.pop("decision_id", ""))
                    if args or not decision_id:
                        return {
                            "success": False,
                            "error": "knowledge undo requires decision_id and optional reason",
                        }
                    from harness_mem.commands.knowledge_assimilation import (
                        undo_separated_review,
                    )

                    result = asyncio.run(
                        undo_separated_review(
                            _get_backend(),
                            decision_id=decision_id,
                            reason=str(reason or "review undo"),
                            expected_project_name=project_name,
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
                        "supersede",
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
                return {"governance_action": action, "success": True, **result}
            if args:
                return {
                    "success": False,
                    "error": f"unexpected decide arguments: {sorted(args)}",
                }
            decision_handlers: dict[tuple[str, str], Callable[[], dict[str, Any]]] = {
                ("memory", "confirm"): lambda: tool_confirm_memory_entry(candidate_id),
                ("memory", "reject"): lambda: tool_reject_memory_entry(candidate_id),
                ("rule", "confirm"): lambda: tool_confirm_rule(candidate_id),
                ("rule", "reject"): lambda: tool_reject_rule(
                    candidate_id, reason=reason
                ),
                ("relation", "confirm"): lambda: tool_confirm_relation_fact(
                    candidate_id
                ),
                ("relation", "reject"): lambda: tool_reject_relation_fact(candidate_id),
            }
            handler = decision_handlers.get((kind, decision))
            if handler is None or not candidate_id:
                return {
                    "success": False,
                    "error": "decide requires kind=memory|rule|relation, decision=confirm|reject, and candidate_id",
                }
            result = handler()
        elif action == "handoff":
            result = tool_create_task_handoff(**args)
        elif action == "correct_rule":
            result = tool_suggest_correction(**args)
        elif action == "supersede":
            decision = str(args.pop("decision", "suggest"))
            if decision == "suggest":
                result = tool_suggest_supersede(**args)
            else:
                candidate_id = str(args.pop("candidate_id", ""))
                if args or decision not in {"confirm", "reject"} or not candidate_id:
                    return {
                        "success": False,
                        "error": "supersede decision requires confirm|reject and candidate_id",
                    }
                result = (
                    tool_confirm_supersede(candidate_id)
                    if decision == "confirm"
                    else tool_reject_supersede(candidate_id)
                )
        else:
            return {"success": False, "error": "unknown governance action"}
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"invalid {action} arguments: {exc}"}
    return {"governance_action": action, **result}
