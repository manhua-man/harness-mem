"""Pure helpers shared by structured-store capability slices."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_SEARCH_SCORE_FIELDS = (
    "_fts_score",
    "_fts_score_total",
    "_fts_match_count",
    "_fts_rank",
    "_vec_rank",
    "_vec_sim",
    "_fts_factor",
    "_vec_factor",
    "_rrf_score",
    "_hybrid_score",
    "_score",
)


def _copy_search_score_fields(data: dict[str, Any], row: dict[str, Any]) -> None:
    for field in _SEARCH_SCORE_FIELDS:
        if field in row:
            data[field] = row[field]


def _normalize_time_window(
    time_window: tuple[datetime | None, datetime | None],
) -> tuple[datetime | None, datetime | None]:
    start, end = time_window
    return _normalize_datetime(start), _normalize_datetime(end)


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


def _has_superseded_by(data: dict[str, Any]) -> bool:
    superseded_by = data.get("superseded_by")
    if superseded_by is None:
        return False
    if isinstance(superseded_by, str):
        stripped = superseded_by.strip()
        return stripped not in {"", "[]"}
    if isinstance(superseded_by, list):
        return bool(superseded_by)
    return bool(superseded_by)
