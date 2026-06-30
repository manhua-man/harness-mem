"""Review policy helpers for session-distill."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .distill_rules import map_candidate_readiness
from .models import CandidateDraft, Packet, ReadinessDecision

ReviewMode = Literal["preview", "apply-low-risk"]
DEFAULT_REVIEW_MODE: ReviewMode = "apply-low-risk"


@dataclass(frozen=True)
class ReviewPolicy:
    mode: ReviewMode = DEFAULT_REVIEW_MODE
    apply: bool = True

    @property
    def preview_only(self) -> bool:
        return not self.apply


@dataclass(frozen=True)
class ReviewPlan:
    policy: ReviewPolicy
    decisions: tuple[ReadinessDecision, ...]

    @property
    def preview_only(self) -> bool:
        return self.policy.preview_only


def default_review_policy() -> ReviewPolicy:
    return review_policy_for_mode(DEFAULT_REVIEW_MODE)


def review_policy_for_mode(mode: ReviewMode) -> ReviewPolicy:
    return ReviewPolicy(mode=mode, apply=(mode == "apply-low-risk"))


def plan_review(
    drafts: list[CandidateDraft],
    packet: Packet,
    policy: ReviewPolicy | None = None,
) -> ReviewPlan:
    active_policy = policy or default_review_policy()
    decisions = tuple(map_candidate_readiness(draft, packet.audit) for draft in drafts)
    return ReviewPlan(policy=active_policy, decisions=decisions)
