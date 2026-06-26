"""Pure distillation boundary rules."""

from __future__ import annotations

from .models import CandidateDraft, PacketAudit, ReadinessDecision


def map_candidate_readiness(
    draft: CandidateDraft,
    audit: PacketAudit,
) -> ReadinessDecision:
    """Map draft readiness to harness-mem export/review boundaries."""

    if draft.readiness == "ephemeral":
        return ReadinessDecision(
            readiness="ephemeral",
            exportable=False,
            auto_apply_allowed=False,
            skip_reason="ephemeral",
        )

    if draft.readiness == "local-only":
        return ReadinessDecision(
            readiness="local-only",
            exportable=False,
            auto_apply_allowed=False,
            skip_reason="local_only",
        )

    if draft.readiness == "needs-conflict-review":
        return ReadinessDecision(
            readiness="needs-conflict-review",
            exportable=True,
            auto_apply_allowed=False,
            requires_manual_review=True,
            blocked_reason="conflict_review_required",
        )

    if draft.readiness == "needs-raw-review" or audit.is_partial:
        return ReadinessDecision(
            readiness="needs-raw-review",
            exportable=True,
            auto_apply_allowed=False,
            blocked_reason="raw_review_required",
        )

    return ReadinessDecision(
        readiness="ready-candidate",
        exportable=True,
        auto_apply_allowed=True,
    )
