"""Lifecycle tier scoring and candidate selection.

v4.0.4 makes hot/warm/cold/archive a first-class read-path concept.  The
scorer here is intentionally pure: it proposes tier changes, but never mutates
confirmed truth.  Write-side workflows can persist the returned drafts through
candidate/ledger surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal


LifecycleTier = Literal["hot", "warm", "cold", "archive"]
_TIER_ORDER: dict[str, int] = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}


@dataclass(frozen=True)
class LifecycleCandidate:
    target_id: str
    candidate_kind: str
    from_tier: LifecycleTier
    to_tier: LifecycleTier
    reason: str
    confidence: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "candidate_kind": self.candidate_kind,
            "from_tier": self.from_tier,
            "to_tier": self.to_tier,
            "reason": self.reason,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


def score_lifecycle_tier(entry: object, *, now: datetime | None = None) -> tuple[LifecycleTier, str, float]:
    """Return recommended lifecycle tier without mutating ``entry``."""

    reference = _normalize_datetime(now) or datetime.now(timezone.utc)
    decay_score = _float_or(getattr(entry, "decay_score", None), 0.0)
    usage_count = int(getattr(entry, "usage_count", 0) or 0)
    last_accessed = _normalize_datetime(getattr(entry, "last_accessed_at", None))
    created_at = _normalize_datetime(getattr(entry, "created_at", None))
    observed = last_accessed or created_at
    age_days = (reference - observed).days if observed else 0

    if decay_score >= 0.9 or age_days >= 180:
        return "archive", "very stale or high decay score", min(0.95, max(decay_score, 0.75))
    if age_days >= 90:
        return "cold", "not surfaced for at least 90 days", max(0.65, decay_score)
    if age_days >= 30 and usage_count <= 1:
        return "warm", "low recent access", max(0.55, decay_score)
    return "hot", "recent or frequently accessed", max(0.5, 1.0 - min(age_days, 30) / 60)


def select_lifecycle_tier_candidates(
    entries: Iterable[object],
    *,
    now: datetime | None = None,
) -> list[LifecycleCandidate]:
    """Return downgrade/archive candidates; never changes the source entries."""

    candidates: list[LifecycleCandidate] = []
    for entry in entries:
        target_id = str(getattr(entry, "id", "") or "")
        if not target_id:
            continue
        current = _normalize_tier(getattr(entry, "tier", "hot"))
        recommended, reason, confidence = score_lifecycle_tier(entry, now=now)
        if _TIER_ORDER[recommended] <= _TIER_ORDER[current]:
            continue
        observed = _normalize_datetime(getattr(entry, "last_accessed_at", None)) or _normalize_datetime(
            getattr(entry, "created_at", None)
        )
        reference = _normalize_datetime(now) or datetime.now(timezone.utc)
        age_days = max(0, (reference - observed).days) if observed else 0
        candidates.append(
            LifecycleCandidate(
                target_id=target_id,
                candidate_kind="tier_downgrade",
                from_tier=current,
                to_tier=recommended,
                reason=reason,
                confidence=round(confidence, 3),
                metadata={
                    "usage_count": int(getattr(entry, "usage_count", 0) or 0),
                    "last_accessed_at": _iso_or_none(
                        getattr(entry, "last_accessed_at", None)
                    ),
                    "created_at": _iso_or_none(getattr(entry, "created_at", None)),
                    "age_days": age_days,
                    "decay_score": _float_or(getattr(entry, "decay_score", None), 0.0),
                },
            )
        )
    candidates.sort(key=lambda item: (-item.confidence, item.target_id))
    return candidates


async def persist_lifecycle_tier_candidates(
    structured_store: object,
    candidates: Iterable[LifecycleCandidate],
    *,
    project_name: str,
    metabolism_run_id: str = "lifecycle-tiering",
    target_kind: Literal["memory_entry", "confirmed_rule", "relation_fact"] = "memory_entry",
) -> list[str]:
    """Persist lifecycle proposals through the existing reviewable candidate queue.

    Tiering is governance: this helper writes pending stale-truth suggestion
    candidates with lifecycle metadata, and never edits the target truth row.
    """

    from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
        StaleTruthSuggestionCandidate,
    )

    save = getattr(structured_store, "save_stale_truth_suggestion_candidate", None)
    if save is None:
        raise TypeError("structured_store must support stale truth suggestion candidates")

    saved: list[str] = []
    for candidate in candidates:
        proposal = StaleTruthSuggestionCandidate.model_validate(
            {
                "project_name": project_name,
                "target_id": candidate.target_id,
                "target_kind": target_kind,
                "last_surfaced_at": _normalize_datetime(
                    candidate.metadata.get("last_accessed_at")
                ),
                "days_since_last_surface": int(candidate.metadata.get("age_days") or 0),
                "evidence_signal_ids": [],
                "metabolism_run_id": metabolism_run_id,
                "lifecycle_candidate_kind": candidate.candidate_kind,
                "from_tier": candidate.from_tier,
                "to_tier": candidate.to_tier,
                "lifecycle_reason": candidate.reason,
                "confidence": candidate.confidence,
                "lifecycle_metadata": dict(candidate.metadata),
            }
        )
        saved.append(await save(proposal))
    return saved


def _normalize_tier(value: object) -> LifecycleTier:
    text = str(value or "hot")
    if text in _TIER_ORDER:
        return text  # type: ignore[return-value]
    return "hot"


def _normalize_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        normalized = value
    elif isinstance(value, str) and value:
        try:
            normalized = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized


def _iso_or_none(value: object) -> str | None:
    normalized = _normalize_datetime(value)
    return normalized.isoformat() if normalized else None


def _float_or(value: object, fallback: float) -> float:
    if value is None or isinstance(value, bool):
        return fallback
    if not isinstance(value, (str, int, float)):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


__all__ = [
    "LifecycleCandidate",
    "LifecycleTier",
    "persist_lifecycle_tier_candidates",
    "score_lifecycle_tier",
    "select_lifecycle_tier_candidates",
]
