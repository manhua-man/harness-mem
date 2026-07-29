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

# ``procedural`` gets quota=0 by default and appears only when the user raises
# its configured wake quota.
BUCKET_ORDER: tuple[str, ...] = ("semantic", "episodic", "procedural")


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


def select_wake_memory_entries_with_buckets(
    entries: list[Any],
    *,
    limit: int = 5,
    quotas: dict[str, float],
    enabled: bool = True,
) -> tuple[list[Any], dict[str, "BucketStats"]]:
    """按 ``memory_type`` 分桶选 entry，返回 ``(selected, stats_per_bucket)``。

    - ``enabled=False`` 时退化到 ``select_wake_memory_entries``，并返回空 stats。
    - 桶名额 = ``floor(limit * quota)``。剩余名额按 ``BUCKET_ORDER`` 优先级让渡，
      但绝不让渡到 quota=0 的桶（避免重新填 procedural）。
    - 桶内排序复用既有 importance + recency 算法。
    - 输出顺序：先 ``semantic`` 桶的全部，再 ``episodic`` 桶的全部，再 ``procedural``
      桶的全部——和 wake-up 输出阅读顺序一致。
    """
    if not enabled or limit <= 0 or not entries:
        legacy = select_wake_memory_entries(entries, limit=limit) if enabled else []
        if not enabled:
            legacy = select_wake_memory_entries(entries, limit=limit)
        return legacy, {}

    raw_quota_count = {bucket: int(limit * quotas.get(bucket, 0.0)) for bucket in BUCKET_ORDER}
    # 把 limit 与 floor 之差当成可让渡余量（按 BUCKET_ORDER 顺序优先 semantic）
    leftover_total = limit - sum(raw_quota_count.values())
    if leftover_total > 0:
        for bucket in BUCKET_ORDER:
            if quotas.get(bucket, 0.0) <= 0.0:
                continue
            if leftover_total <= 0:
                break
            raw_quota_count[bucket] += 1
            leftover_total -= 1

    # 分桶
    buckets: dict[str, list[Any]] = {bucket: [] for bucket in BUCKET_ORDER}
    for entry in entries:
        bucket = _bucket_for_entry(entry)
        buckets.setdefault(bucket, []).append(entry)

    # 桶内 importance 优先 + recency 次序
    for bucket in buckets:
        buckets[bucket] = _bucket_sorted(buckets[bucket])

    # 让渡：未消费的名额按 BUCKET_ORDER 让给 quota>0 的桶
    final_quota = dict(raw_quota_count)
    for source_bucket in BUCKET_ORDER:
        excess = final_quota[source_bucket] - len(buckets.get(source_bucket, []))
        if excess <= 0:
            continue
        final_quota[source_bucket] -= excess
        for target_bucket in BUCKET_ORDER:
            if target_bucket == source_bucket:
                continue
            if quotas.get(target_bucket, 0.0) <= 0.0:
                continue
            available = len(buckets.get(target_bucket, [])) - final_quota[target_bucket]
            if available <= 0:
                continue
            take = min(available, excess)
            final_quota[target_bucket] += take
            excess -= take
            if excess <= 0:
                break

    # 选取 + 截断
    selected: list[Any] = []
    stats: dict[str, BucketStats] = {}
    for bucket in BUCKET_ORDER:
        candidates = buckets.get(bucket, [])
        quota_count_value = final_quota[bucket]
        chosen = candidates[:quota_count_value]
        selected.extend(chosen)
        stats[bucket] = BucketStats(
            quota=quotas.get(bucket, 0.0),
            quota_count=raw_quota_count[bucket],
            used=len(chosen),
            candidates=len(candidates),
            truncated=len(candidates) > quota_count_value,
        )
    return selected, stats


class BucketStats:
    """单桶的填充统计，wake-up header 与 truncation 行用它格式化。"""

    __slots__ = ("quota", "quota_count", "used", "candidates", "truncated")

    def __init__(
        self,
        *,
        quota: float,
        quota_count: int,
        used: int,
        candidates: int,
        truncated: bool,
    ) -> None:
        self.quota = quota
        self.quota_count = quota_count
        self.used = used
        self.candidates = candidates
        self.truncated = truncated


def _bucket_for_entry(entry: Any) -> str:
    raw = getattr(entry, "memory_type", None) or "semantic"
    bucket = str(raw).lower()
    if bucket not in BUCKET_ORDER:
        return "semantic"
    return bucket


def _bucket_sorted(entries: list[Any]) -> list[Any]:
    """复用 ``select_wake_memory_entries`` 的"importance 优先 + recency"启发式。

    注意：这里不再做 ``PROTECTED_SCORE_THRESHOLD`` 截断——分桶预算下的"保护"已经
    由桶配额本身完成。
    """
    return sorted(entries, key=_combined_key, reverse=True)


def _combined_key(entry: Any) -> tuple[float, float]:
    return _importance_score(entry), _recency_key(entry)


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
