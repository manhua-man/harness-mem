"""Pure serializer helpers for MCP candidate payloads.

Extracted from :mod:`harness_mem.mcp.server` so the server module stays
focused on JSON-RPC plumbing and tool registration. Every function here
is **stateless and side-effect-free**: same input -> same dict output,
no backend, no IO, no global state. This is the safest first cut at
the long-term server.py split documented in the server module's
docstring.

If you find yourself wanting to add a serializer that touches a backend,
hits the filesystem, or depends on configuration — that's a tool, not a
serializer. Put it in ``server.py`` (or, when the proper split lands,
``mcp/tools/<category>.py``).
"""

from __future__ import annotations

from typing import Any


def _isoformat(value: Any) -> str | None:
    """Return ``value.isoformat()`` when available, else ``str(value)``.

    Returns ``None`` for ``None`` so callers don't have to guard.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_rule_candidate(candidate: Any) -> dict:
    return {
        "type": "rule",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "examples": candidate.examples,
        "confidence": candidate.confidence,
        "source_session_id": candidate.session_id,
        "created_at": _isoformat(candidate.created_at),
        "confirm_tool": "confirm_rule",
        "reject_tool": "reject_rule",
    }


def _serialize_memory_entry_candidate(entry: Any) -> dict:
    return {
        "type": "memory_entry",
        "id": entry.id,
        "project_name": entry.project_name,
        "status": entry.status,
        "category": entry.category,
        "memory_type": getattr(entry, "memory_type", None),
        "content": entry.content,
        "confidence": entry.confidence,
        "source": entry.source,
        "tags": entry.tags,
        "created_at": _isoformat(entry.created_at),
        "updated_at": _isoformat(entry.updated_at),
        "provenance": entry.provenance,
        "confirm_tool": "confirm_memory_entry",
        "reject_tool": "reject_memory_entry",
    }


def _serialize_relation_fact_candidate(fact: Any) -> dict:
    return {
        "type": "relation_fact",
        "id": fact.id,
        "project_name": fact.project_name,
        "status": fact.status,
        "source_entity": fact.source_entity,
        "target_entity": fact.target_entity,
        "relation_type": fact.relation_type,
        "evidence": fact.evidence,
        "source": fact.source,
        "confidence": fact.confidence,
        "tags": fact.tags,
        "created_at": _isoformat(fact.created_at),
        "updated_at": _isoformat(fact.updated_at),
        "provenance": fact.provenance,
        "confirm_tool": "confirm_relation_fact",
        "reject_tool": "reject_relation_fact",
    }


def _serialize_supersede_candidate(candidate: Any) -> dict:
    return {
        "type": "supersede",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "target_type": candidate.target_type,
        "target_id": candidate.target_id,
        "replacement_type": candidate.replacement_type,
        "replacement_id": candidate.replacement_id,
        "reason": candidate.reason,
        "evidence": candidate.evidence,
        "confidence": candidate.confidence,
        "source": candidate.source,
        "created_at": _isoformat(candidate.created_at),
        "reviewed_at": _isoformat(candidate.reviewed_at),
        "reviewer_id": candidate.reviewer_id,
        "confirm_tool": "confirm_supersede",
        "reject_tool": "reject_supersede",
    }


def _serialize_procedural_candidate(candidate: Any) -> dict:
    return {
        "type": "procedural",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "activation_condition": candidate.activation_condition,
        "steps": candidate.steps,
        "termination_condition": candidate.termination_condition,
        "success_examples": candidate.success_examples,
        "source_session_id": candidate.source_session_id,
        "source": candidate.source,
        "confidence": candidate.confidence,
        "created_at": _isoformat(candidate.created_at),
        "confirm_tool": None,
        "reject_tool": None,
        "review_surface": "skill_governance_internal",
    }


def _serialize_merge_suggestion_candidate(candidate: Any) -> dict:
    return {
        "type": "merge_suggestion",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "target_a_id": candidate.target_a_id,
        "target_a_kind": candidate.target_a_kind,
        "target_b_id": candidate.target_b_id,
        "target_b_kind": candidate.target_b_kind,
        "proposed_content": candidate.proposed_content,
        "similarity_score": candidate.similarity_score,
        "evidence_signal_ids": list(candidate.evidence_signal_ids),
        "metabolism_run_id": candidate.metabolism_run_id,
        "created_at": _isoformat(candidate.created_at),
    }


def _serialize_stale_truth_suggestion_candidate(candidate: Any) -> dict:
    return {
        "type": "stale_truth_suggestion",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "target_id": candidate.target_id,
        "target_kind": candidate.target_kind,
        "last_surfaced_at": _isoformat(candidate.last_surfaced_at),
        "days_since_last_surface": candidate.days_since_last_surface,
        "evidence_signal_ids": list(candidate.evidence_signal_ids),
        "metabolism_run_id": candidate.metabolism_run_id,
        "created_at": _isoformat(candidate.created_at),
    }
