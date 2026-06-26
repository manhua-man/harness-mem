"""Suggest-only export planning for harness-mem candidates."""

from __future__ import annotations

from .distill_rules import map_candidate_readiness
from .models import CandidateDraft, Packet, SuggestCall, SuggestToolName

KIND_TO_SUGGEST_TOOL: dict[str, SuggestToolName] = {
    "memory_entry": "suggest_memory_entry",
    "rule": "suggest_rule",
    "relation_fact": "suggest_relation_fact",
    "task_handoff": "create_task_handoff",
}


def build_suggest_calls(
    drafts: list[CandidateDraft],
    packet: Packet,
    *,
    current_session_id: str | None = None,
) -> list[SuggestCall]:
    """Convert drafts to harness-mem suggest calls.

    The returned plan never includes confirm/reject/replace operations and never
    writes durable truth directly.
    """

    calls: list[SuggestCall] = []
    for draft in drafts:
        if _is_self_session_draft(draft, packet, current_session_id):
            continue
        decision = map_candidate_readiness(draft, packet.audit)
        if not decision.exportable:
            continue

        tool_name = KIND_TO_SUGGEST_TOOL[draft.kind]
        arguments = _suggest_arguments(draft, packet)
        arguments["readiness"] = decision.readiness
        if decision.blocked_reason:
            arguments["blocked_reason"] = decision.blocked_reason
        if decision.requires_manual_review:
            arguments["requires_manual_review"] = True
        calls.append(SuggestCall(tool_name=tool_name, arguments=arguments, decision=decision))

    return calls


def _is_self_session_draft(
    draft: CandidateDraft,
    packet: Packet,
    current_session_id: str | None,
) -> bool:
    if current_session_id and (
        packet.session_id == current_session_id
        or draft.source_session_id == current_session_id
    ):
        return True

    metadata = packet.metadata
    if metadata.get("session_distill_self") is True:
        return True
    if metadata.get("is_self_session") is True:
        return True
    return metadata.get("origin") == "session-distill"


def _suggest_arguments(draft: CandidateDraft, packet: Packet) -> dict[str, object]:
    project_name = packet.project_name or draft.metadata.get("project_name")
    source_session_id = draft.source_session_id or packet.session_id
    base: dict[str, object] = {
        "project_name": project_name,
        "source": f"session-distill:{source_session_id}",
    }

    if draft.kind == "memory_entry":
        base.update(
            {
                "category": draft.category or "decision",
                "content": draft.content,
                "confidence": draft.metadata.get("confidence", 0.7),
                "tags": ["session-distill"],
            }
        )
    elif draft.kind == "rule":
        base.update(
            {
                "pattern": draft.content,
                "trigger": draft.metadata.get("trigger", draft.content[:120]),
                "session_id": source_session_id,
                "examples": list(draft.evidence),
            }
        )
    elif draft.kind == "relation_fact":
        base.update(
            {
                "source_entity": draft.source_entity,
                "target_entity": draft.target_entity,
                "relation_type": draft.relation_type or "associated_with",
                "evidence": draft.content,
                "confidence": draft.metadata.get("confidence", 0.7),
            }
        )
    elif draft.kind == "task_handoff":
        base.update(
            {
                "task_id": draft.metadata.get("task_id", source_session_id),
                "summary": draft.content,
                "status": draft.metadata.get("status", "pending"),
                "next_steps": draft.metadata.get("next_steps", []),
                "blockers": draft.metadata.get("blockers", []),
            }
        )

    return base
