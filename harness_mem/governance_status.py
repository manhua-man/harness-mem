"""Governance status tiers for auto-promoted memory with post-hoc audit."""

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
    "accepted",
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
        "accepted",
    }
)

CANDIDATE_LAYER_STATUSES: frozenset[str] = frozenset(
    {"pending", "deferred", "rejected"}
)

READABLE_FULL_WEIGHT: frozenset[str] = frozenset(
    {"accepted", "auto_confirmed", "user_confirmed"}
)

PROVISIONAL_STATUS = "provisional"

INVISIBLE_STATUSES: frozenset[str] = frozenset(
    {"pending", "deferred", "rejected"}
)

USER_CONFIRMED_STATUS = "user_confirmed"
AUTO_CONFIRMED_STATUS = "auto_confirmed"
SUPERSEDED_STATUS = "superseded"
DEFERRED_STATUS = "deferred"
LEGACY_ACCEPTED_STATUS = "accepted"

PROVISIONAL_TRUTH_WEIGHT = 0.6
FULL_TRUTH_WEIGHT = 1.0

# pending -> promoted / deferred / rejected
_PENDING_TARGETS = frozenset(
    {
        "auto_confirmed",
        "provisional",
        "deferred",
        "rejected",
        USER_CONFIRMED_STATUS,
        LEGACY_ACCEPTED_STATUS,
    }
)
# auto paths -> user audit or lineage
_AUTO_TARGETS = frozenset({"user_confirmed", "superseded", "rejected"})
_PROVISIONAL_TARGETS = frozenset({"user_confirmed", "superseded", "rejected"})
_DEFERRED_TARGETS = frozenset({"pending", "rejected", USER_CONFIRMED_STATUS})
_LEGACY_ACCEPTED_TARGETS = frozenset({"user_confirmed", "superseded"})


def normalize_status_on_load(status: str | None) -> str:
    """Preserve stored status; default missing values to legacy accepted."""
    if not status:
        return LEGACY_ACCEPTED_STATUS
    return status


def is_valid_governance_status(status: str) -> bool:
    return status in GOVERNANCE_STATUSES


def is_readable_truth(
    status: str,
    *,
    include_provisional: bool = False,
) -> bool:
    if status in READABLE_FULL_WEIGHT:
        return True
    return include_provisional and status == PROVISIONAL_STATUS


def truth_weight(status: str) -> float:
    if status in READABLE_FULL_WEIGHT:
        return FULL_TRUTH_WEIGHT
    if status == PROVISIONAL_STATUS:
        return PROVISIONAL_TRUTH_WEIGHT
    return 0.0


def statuses_for_list_filter(
    status: str = LEGACY_ACCEPTED_STATUS,
    *,
    include_provisional: bool = False,
    include_superseded: bool = False,
) -> list[str]:
    """Resolve a list/filter status token to concrete stored statuses."""
    if status == LEGACY_ACCEPTED_STATUS:
        resolved = list(READABLE_FULL_WEIGHT)
        if include_provisional:
            resolved.append(PROVISIONAL_STATUS)
        if include_superseded:
            resolved.append(SUPERSEDED_STATUS)
        return resolved
    return [status]


def validate_status_transition(from_status: str, to_status: str) -> bool:
    """Return whether a governance transition is allowed."""
    if from_status == to_status:
        return True
    if not is_valid_governance_status(from_status) or not is_valid_governance_status(
        to_status
    ):
        return False

    if from_status == "pending":
        return to_status in _PENDING_TARGETS
    if from_status in {AUTO_CONFIRMED_STATUS, LEGACY_ACCEPTED_STATUS}:
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