"""User-facing summary helpers."""

from __future__ import annotations

from collections import Counter

from .distill_rules import map_candidate_readiness
from .models import CandidateDraft, Packet, ReadinessDecision
from .review_policy import ReviewPlan


def candidate_counts(drafts: list[CandidateDraft]) -> dict[str, int]:
    return dict(Counter(draft.kind for draft in drafts))


def readiness_counts(
    drafts: list[CandidateDraft],
    packet: Packet,
) -> dict[str, int]:
    decisions = [map_candidate_readiness(draft, packet.audit) for draft in drafts]
    counts = Counter(decision.readiness for decision in decisions)
    counts["blocked"] = sum(1 for decision in decisions if decision.blocked_reason)
    counts["manual_review"] = sum(
        1 for decision in decisions if decision.requires_manual_review
    )
    counts["local_only"] = sum(1 for decision in decisions if decision.skip_reason == "local_only")
    counts["ephemeral"] = sum(1 for decision in decisions if decision.skip_reason == "ephemeral")
    return dict(counts)


def review_decision_counts(decisions: tuple[ReadinessDecision, ...]) -> dict[str, int]:
    counts = Counter(decision.readiness for decision in decisions)
    counts["blocked"] = sum(1 for decision in decisions if decision.blocked_reason)
    counts["manual_review"] = sum(
        1 for decision in decisions if decision.requires_manual_review
    )
    return dict(counts)


def default_distill_summary(
    *,
    packet: Packet,
    drafts: list[CandidateDraft],
    review_plan: ReviewPlan,
) -> str:
    counts = candidate_counts(drafts)
    readiness = readiness_counts(drafts, packet)
    review_counts = review_decision_counts(review_plan.decisions)
    raw_review = "yes" if packet.audit.is_partial else "no"
    lines = [
        "Distill completed.",
        "",
        "Packet:",
        f"- session: {packet.session_id}",
        f"- coverage: {packet.audit.coverage}",
        f"- raw review required: {raw_review}",
        "",
        "Candidates suggested:",
    ]
    for kind in ("memory_entry", "rule", "relation_fact", "task_handoff"):
        lines.append(f"- {kind}: {counts.get(kind, 0)}")
    lines.extend(
        [
            f"- ready-candidate: {readiness.get('ready-candidate', 0)}",
            f"- blocked/raw-review: {readiness.get('needs-raw-review', 0)}",
            f"- conflict-review: {readiness.get('needs-conflict-review', 0)}",
            f"- local-only: {readiness.get('local_only', 0)}",
            f"- ephemeral: {readiness.get('ephemeral', 0)}",
        ]
    )
    lines.extend(
        [
            "",
            "Review:",
            f"- auto-review mode: {review_plan.policy.mode}",
            f"- blocked decisions: {review_counts.get('blocked', 0)}",
            f"- manual review required: {review_counts.get('manual_review', 0)}",
            "- low-risk decisions may be auto-promoted with audit metadata",
            "- run /hm:review to audit/confirm/reject/undo/replace",
        ]
    )
    return "\n".join(lines)
