"""Governance status tiers: candidate / truth / historical layers."""

from __future__ import annotations

from typing import Literal

GovernanceStatus = Literal[
    "pending",
    "deferred",
    "rejected",
    "auto_confirmed",
    "provisional",
    "user_confirmed",
    "superseded",
]

GOVERNANCE_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "deferred",
        "rejected",
        "auto_confirmed",
        "provisional",
        "user_confirmed",
        "superseded",
    }
)

GOVERNANCE_STATUS_LIST: tuple[str, ...] = (
    "pending",
    "deferred",
    "rejected",
    "auto_confirmed",
    "provisional",
    "user_confirmed",
    "superseded",
)

LEGACY_ACCEPTED_STATUS = "accepted"
"""Pre-0.8.9 blob status; invisible to readable_truth (doctor reports only)."""

LIST_CANDIDATES_STATUS_DESCRIPTION = (
    "Governance status filter (single value). Layers: candidate "
    "(pending, deferred, rejected); truth (auto_confirmed, provisional, "
    "user_confirmed); historical (superseded). Audit inbox typically uses "
    "pending, provisional, or auto_confirmed — not all seven interchangeably."
)

AUDIT_INBOX_STATUSES: frozenset[str] = frozenset(
    {"pending", "provisional", "auto_confirmed"}
)

# Layer sets (not parallel enums — runtime routes by layer).
CANDIDATE_LAYER_STATUSES: frozenset[str] = frozenset(
    {"pending", "deferred", "rejected"}
)
TRUTH_LAYER_STATUSES: frozenset[str] = frozenset(
    {"auto_confirmed", "provisional", "user_confirmed"}
)
TRUTH_LAYER_FULL_WEIGHT: frozenset[str] = frozenset(
    {"auto_confirmed", "user_confirmed"}
)
HISTORICAL_LAYER_STATUSES: frozenset[str] = frozenset({"superseded"})

READABLE_TRUTH_FILTER = "readable_truth"
"""List/search filter token: truth-layer entries at full weight."""

PROVISIONAL_STATUS = "provisional"
INVISIBLE_STATUSES: frozenset[str] = CANDIDATE_LAYER_STATUSES

USER_CONFIRMED_STATUS = "user_confirmed"
AUTO_CONFIRMED_STATUS = "auto_confirmed"
SUPERSEDED_STATUS = "superseded"
DEFERRED_STATUS = "deferred"

PROVISIONAL_TRUTH_WEIGHT = 0.6
FULL_TRUTH_WEIGHT = 1.0

# Maintenance review candidates (dream supersede/merge/stale) — not truth-layer
# statuses; kept separate so we do not overload memory governance transitions.
MAINTENANCE_REVIEW_STATUSES: frozenset[str] = frozenset(
    {"pending", "rejected", "user_confirmed"}
)
MAINTENANCE_REVIEW_COLLECTIONS: frozenset[str] = frozenset(
    {
        "supersede_candidates",
        "merge_suggestion_candidates",
        "stale_truth_suggestion_candidates",
        "procedural_candidates",
    }
)

_PENDING_TARGETS = frozenset(
    {
        AUTO_CONFIRMED_STATUS,
        PROVISIONAL_STATUS,
        DEFERRED_STATUS,
        "rejected",
        USER_CONFIRMED_STATUS,
    }
)
_AUTO_TARGETS = frozenset({USER_CONFIRMED_STATUS, SUPERSEDED_STATUS, "rejected"})
_PROVISIONAL_TARGETS = frozenset({USER_CONFIRMED_STATUS, SUPERSEDED_STATUS, "rejected"})
_DEFERRED_TARGETS = frozenset({"pending", "rejected", USER_CONFIRMED_STATUS})


def normalize_status_on_load(status: str | None) -> str:
    """Default missing candidate records to pending."""
    if not status:
        return "pending"
    return status


def is_governed_truth_collection(collection: str) -> bool:
    return collection not in MAINTENANCE_REVIEW_COLLECTIONS


def is_valid_governance_status(status: str) -> bool:
    return status in GOVERNANCE_STATUSES


def is_valid_maintenance_review_status(status: str) -> bool:
    return status in MAINTENANCE_REVIEW_STATUSES


def validate_maintenance_review_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return True
    if from_status == "pending":
        return to_status in {USER_CONFIRMED_STATUS, "rejected"}
    return False


def is_readable_truth(
    status: str,
    *,
    include_provisional: bool = False,
) -> bool:
    if status in TRUTH_LAYER_FULL_WEIGHT:
        return True
    return include_provisional and status == PROVISIONAL_STATUS


def truth_weight(status: str) -> float:
    if status in TRUTH_LAYER_FULL_WEIGHT:
        return FULL_TRUTH_WEIGHT
    if status == PROVISIONAL_STATUS:
        return PROVISIONAL_TRUTH_WEIGHT
    return 0.0


def statuses_for_list_filter(
    status: str = READABLE_TRUTH_FILTER,
    *,
    include_provisional: bool = False,
    include_superseded: bool = False,
) -> list[str]:
    """Resolve a list/search filter token to concrete truth-layer statuses."""
    if status == READABLE_TRUTH_FILTER:
        resolved = list(TRUTH_LAYER_FULL_WEIGHT)
        if include_provisional:
            resolved.append(PROVISIONAL_STATUS)
        if include_superseded:
            resolved.append(SUPERSEDED_STATUS)
        return resolved
    return [status]


def validate_status_transition(from_status: str, to_status: str) -> bool:
    """Truth/candidate governance transitions for memory/rule/relation records."""
    if from_status == to_status:
        return True
    if not is_valid_governance_status(from_status) or not is_valid_governance_status(
        to_status
    ):
        return False

    if from_status == "pending":
        return to_status in _PENDING_TARGETS
    if from_status == AUTO_CONFIRMED_STATUS:
        return to_status in _AUTO_TARGETS
    if from_status == PROVISIONAL_STATUS:
        return to_status in _PROVISIONAL_TARGETS
    if from_status == USER_CONFIRMED_STATUS:
        return to_status in {SUPERSEDED_STATUS, "rejected"}
    if from_status == DEFERRED_STATUS:
        return to_status in _DEFERRED_TARGETS
    if from_status == "rejected":
        return False
    if from_status == SUPERSEDED_STATUS:
        return False
    return False


def resolve_promotion_status(
    *,
    action: str,
    kind: str,
    is_high_risk: bool = False,
    confidence: float = 0.0,
) -> str:
    """Map an auto-review action to the target governance status."""
    if action == "auto_reject":
        return "rejected"
    if action == "defer":
        return DEFERRED_STATUS
    if action == "auto_confirm":
        if kind == "rule_candidate":
            return PROVISIONAL_STATUS
        if is_high_risk or confidence < 0.85:
            return PROVISIONAL_STATUS
        return AUTO_CONFIRMED_STATUS
    return "pending"


def user_confirm_status() -> str:
    return USER_CONFIRMED_STATUS