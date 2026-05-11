"""Wake-up memory selection helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any


IMPORTANT_CATEGORIES = {
    "decision": 0.9,
    "architecture": 0.7,
    "convention": 0.6,
    "api": 0.5,
    "bug": 0.4,
}

IMPORTANT_TAGS = {
    "critical": 2.0,
    "expected-wake": 1.5,
    "decision": 0.8,
    "architecture": 0.6,
    "stable": 0.6,
    "rule": 0.5,
}

PROTECTED_SCORE_THRESHOLD = 2.0


def select_wake_memory_entries(entries: list[Any], limit: int = 5) -> list[Any]:
    """Select wake-up memory entries with recency plus importance protection."""
    if limit <= 0 or not entries:
        return []

    recency_ranked = sorted(entries, key=_recency_key, reverse=True)
    protected_count = _protected_slot_count(limit)
    protected = [
        entry
        for entry in sorted(entries, key=_importance_key, reverse=True)
        if _importance_score(entry) >= PROTECTED_SCORE_THRESHOLD
    ][:protected_count]

    selected: list[Any] = []
    seen: set[str] = set()
    for entry in protected:
        entry_id = _entry_id(entry)
        if entry_id in seen:
            continue
        selected.append(entry)
        seen.add(entry_id)

    for entry in recency_ranked:
        if len(selected) >= limit:
            break
        entry_id = _entry_id(entry)
        if entry_id in seen:
            continue
        selected.append(entry)
        seen.add(entry_id)

    return selected


def _protected_slot_count(limit: int) -> int:
    if limit < 3:
        return 0
    return max(1, min(2, limit // 3))


def _importance_key(entry: Any) -> tuple[float, float]:
    return _importance_score(entry), _recency_key(entry)


def _importance_score(entry: Any) -> float:
    score = _float_attr(entry, "confidence", 0.0)
    category = str(getattr(entry, "category", "") or "").lower()
    score += IMPORTANT_CATEGORIES.get(category, 0.0)

    usage_count = max(0, int(_float_attr(entry, "usage_count", 0.0)))
    score += min(usage_count, 5) * 0.2

    for tag in getattr(entry, "tags", []) or []:
        score += IMPORTANT_TAGS.get(str(tag).lower(), 0.0)

    if getattr(entry, "last_accessed_at", None) is not None:
        score += 0.2

    return score


def _recency_key(entry: Any) -> float:
    value = getattr(entry, "updated_at", None) or getattr(entry, "created_at", None)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _entry_id(entry: Any) -> str:
    return str(getattr(entry, "id", id(entry)))


def _float_attr(entry: Any, name: str, default: float) -> float:
    value = getattr(entry, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
