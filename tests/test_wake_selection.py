from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem.core.schemas import MemoryEntry
from harness_mem.wake_selection import select_wake_memory_entries


def test_select_wake_memory_entries_protects_old_critical_entry():
    old_critical = MemoryEntry(
        id="old-critical",
        project_name="demo",
        category="decision",
        content="Old critical decision",
        confidence=0.99,
        source="manual",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=["critical", "expected-wake"],
        usage_count=10,
    )
    recent_entries = [
        MemoryEntry(
            id=f"recent-{index}",
            project_name="demo",
            category="note",
            content=f"Recent routine note {index}",
            confidence=0.5,
            source="manual",
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=index),
            updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=index),
            tags=["routine"],
        )
        for index in range(7)
    ]

    selected = select_wake_memory_entries([old_critical, *recent_entries], limit=5)

    assert [entry.id for entry in selected][:1] == ["old-critical"]
    assert len(selected) == 5


def test_select_wake_memory_entries_does_not_protect_low_value_old_entry():
    old_note = MemoryEntry(
        id="old-note",
        project_name="demo",
        category="note",
        content="Old routine note",
        confidence=0.4,
        source="manual",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=["routine"],
    )
    recent_entries = [
        MemoryEntry(
            id=f"recent-{index}",
            project_name="demo",
            category="note",
            content=f"Recent routine note {index}",
            confidence=0.5,
            source="manual",
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=index),
            updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=index),
        )
        for index in range(5)
    ]

    selected = select_wake_memory_entries([old_note, *recent_entries], limit=5)

    assert "old-note" not in [entry.id for entry in selected]
