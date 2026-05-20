"""Tests for v1.6.1 wake-up bucket budget (semantic / episodic / procedural)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.commands.support import (
    WakeBucketQuotaError,
    wake_bucket_enabled,
    wake_bucket_quotas,
)
from harness_mem.core.schemas import MemoryEntry
from harness_mem.wake_selection import (
    BUCKET_ORDER,
    select_wake_memory_entries_with_buckets,
)


def _entry(
    id: str,
    *,
    memory_type: str = "semantic",
    category: str = "note",
    days: int = 0,
    confidence: float = 0.5,
    tags: list[str] | None = None,
) -> MemoryEntry:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=days)
    return MemoryEntry(
        id=id,
        project_name="demo",
        category=category,
        content=f"content for {id}",
        confidence=confidence,
        source="manual",
        created_at=base,
        updated_at=base,
        tags=tags or [],
        memory_type=memory_type,
    )


DEFAULT_QUOTAS = {"semantic": 0.5, "episodic": 0.5, "procedural": 0.0}


def test_default_quotas_split_evenly_when_both_buckets_full():
    entries = [
        _entry("sem-1", memory_type="semantic", category="decision", days=1, confidence=0.9),
        _entry("sem-2", memory_type="semantic", category="convention", days=2, confidence=0.8),
        _entry("sem-3", memory_type="semantic", category="api", days=3),
        _entry("epi-1", memory_type="episodic", days=4),
        _entry("epi-2", memory_type="episodic", days=5),
        _entry("epi-3", memory_type="episodic", days=6),
    ]
    selected, stats = select_wake_memory_entries_with_buckets(
        entries, limit=4, quotas=DEFAULT_QUOTAS, enabled=True
    )
    assert len(selected) == 4
    sem = [e for e in selected if e.memory_type == "semantic"]
    epi = [e for e in selected if e.memory_type == "episodic"]
    assert len(sem) == 2 and len(epi) == 2
    assert stats["semantic"].used == 2 and stats["episodic"].used == 2
    assert stats["procedural"].used == 0


def test_disabled_bucket_falls_back_to_legacy_selection():
    entries = [
        _entry("sem-1", memory_type="semantic", category="decision", days=10, confidence=0.95),
        _entry("epi-1", memory_type="episodic", days=11),
        _entry("epi-2", memory_type="episodic", days=12),
    ]
    selected, stats = select_wake_memory_entries_with_buckets(
        entries, limit=2, quotas=DEFAULT_QUOTAS, enabled=False
    )
    assert len(selected) == 2
    assert stats == {}


def test_bucket_overflow_truncates_within_bucket_only():
    semantic = [_entry(f"sem-{i}", memory_type="semantic", days=i) for i in range(3)]
    episodic = [_entry(f"epi-{i}", memory_type="episodic", days=10 + i) for i in range(8)]
    selected, stats = select_wake_memory_entries_with_buckets(
        semantic + episodic, limit=5, quotas=DEFAULT_QUOTAS, enabled=True
    )
    used_buckets = {e.memory_type for e in selected}
    assert used_buckets == {"semantic", "episodic"}
    assert stats["semantic"].used <= stats["semantic"].quota_count + 1  # let-through let-renounce
    assert stats["episodic"].truncated is True
    assert stats["episodic"].candidates == 8


def test_bucket_let_through_when_one_bucket_starves():
    """semantic 候选不足时，未消费名额让给 episodic（绝不让给 procedural=0）。"""
    semantic = [_entry("sem-1", memory_type="semantic", days=1)]
    episodic = [_entry(f"epi-{i}", memory_type="episodic", days=10 + i) for i in range(5)]
    procedural = [_entry("proc-1", memory_type="procedural", days=20)]
    selected, stats = select_wake_memory_entries_with_buckets(
        semantic + episodic + procedural,
        limit=5,
        quotas=DEFAULT_QUOTAS,
        enabled=True,
    )
    assert len(selected) == 5
    assert stats["semantic"].used == 1
    assert stats["episodic"].used == 4
    assert stats["procedural"].used == 0


def test_procedural_quota_zero_blocks_procedural_entries():
    procedural = [
        _entry(
            "proc-1",
            memory_type="procedural",
            category="decision",
            confidence=0.99,
            tags=["critical", "expected-wake"],
        )
    ]
    semantic = [_entry("sem-1", memory_type="semantic", days=1)]
    selected, stats = select_wake_memory_entries_with_buckets(
        procedural + semantic, limit=2, quotas=DEFAULT_QUOTAS, enabled=True
    )
    ids = [e.id for e in selected]
    assert "proc-1" not in ids
    assert "sem-1" in ids
    assert stats["procedural"].used == 0


def test_invalid_quota_sum_raises_hm101():
    with pytest.raises(WakeBucketQuotaError) as excinfo:
        wake_bucket_quotas(
            {"wake": {"bucket_quota_semantic": 0.5, "bucket_quota_episodic": 0.6, "bucket_quota_procedural": 0.0}}
        )
    assert excinfo.value.code == "HM-101"
    assert "must sum to 1.0" in str(excinfo.value)


def test_invalid_quota_range_raises_hm102():
    with pytest.raises(WakeBucketQuotaError) as excinfo:
        wake_bucket_quotas(
            {"wake": {"bucket_quota_semantic": -0.1, "bucket_quota_episodic": 0.5, "bucket_quota_procedural": 0.0}}
        )
    assert excinfo.value.code == "HM-102"


def test_default_config_returns_default_quotas():
    quotas = wake_bucket_quotas({})
    assert quotas == {"semantic": 0.5, "episodic": 0.5, "procedural": 0.0}
    for bucket in BUCKET_ORDER:
        assert bucket in quotas


def test_wake_bucket_enabled_default_true():
    assert wake_bucket_enabled({}) is True
    assert wake_bucket_enabled({"wake": {"bucket_quota_enabled": False}}) is False
    assert wake_bucket_enabled({"wake": {"bucket_quota_enabled": "off"}}) is False
