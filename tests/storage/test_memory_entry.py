"""Schema-level tests for MemoryEntry — focuses on the v1.6.0 memory_type field
and the legacy-data derivation rule. Storage-layer behavior lives in
test_local_structured_store.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from harness_mem.core.schemas import MemoryEntry, MemoryType


pytestmark = pytest.mark.storage


# ---------------------------------------------------------------------------
# Default behavior — additive, non-breaking
# ---------------------------------------------------------------------------


def test_new_entry_defaults_to_semantic() -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="convention",
        content="use single quote",
        source="manual",
    )
    assert entry.memory_type == "semantic"


def test_explicit_memory_type_is_preserved() -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="bug",
        content="x",
        source="manual",
        memory_type="episodic",
    )
    assert entry.memory_type == "episodic"


def test_to_dict_emits_memory_type() -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="x",
        source="manual",
    )
    payload = entry.to_dict()
    assert payload["memory_type"] == "semantic"


def test_to_dict_from_dict_round_trip_preserves_memory_type() -> None:
    original = MemoryEntry(
        project_name="demo",
        category="bug",
        content="x",
        source="manual",
        memory_type="episodic",
    )
    rebuilt = MemoryEntry.from_dict(original.to_dict())
    assert rebuilt.memory_type == "episodic"
    assert rebuilt == original


# ---------------------------------------------------------------------------
# Legacy-data derivation rule
# Registered semantic categories: architecture | convention | api | bug | decision
# Anything else (including missing category) -> episodic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    ["architecture", "convention", "api", "bug", "decision"],
)
def test_legacy_data_with_registered_category_derives_to_semantic(
    category: str,
) -> None:
    legacy_blob = {
        "id": "mem_legacy_1",
        "project_name": "demo",
        "category": category,
        "content": "legacy entry",
        "source": "obs_1",
        # Note: memory_type intentionally absent
    }
    entry = MemoryEntry.from_dict(legacy_blob)
    assert entry.memory_type == "semantic"
    assert entry.category == category  # category MUST NOT be modified


def test_legacy_data_with_unknown_category_derives_to_episodic() -> None:
    legacy_blob = {
        "id": "mem_legacy_2",
        "project_name": "demo",
        "category": "raw_note",  # not in registered set
        "content": "legacy entry",
        "source": "obs_1",
    }
    entry = MemoryEntry.from_dict(legacy_blob)
    assert entry.memory_type == "episodic"
    assert entry.category == "raw_note"


def test_legacy_data_with_empty_category_derives_to_episodic() -> None:
    legacy_blob = {
        "id": "mem_legacy_3",
        "project_name": "demo",
        "category": "",
        "content": "legacy entry",
        "source": "obs_1",
    }
    entry = MemoryEntry.from_dict(legacy_blob)
    assert entry.memory_type == "episodic"


def test_legacy_data_with_none_memory_type_still_derives() -> None:
    """Defensive: explicit `null` in JSON should be treated like missing."""
    legacy_blob = {
        "id": "mem_legacy_4",
        "project_name": "demo",
        "category": "convention",
        "content": "legacy entry",
        "source": "obs_1",
        "memory_type": None,
    }
    entry = MemoryEntry.from_dict(legacy_blob)
    assert entry.memory_type == "semantic"


def test_legacy_full_blob_round_trip_remains_compatible() -> None:
    """Mimics a v1.5.x JSON blob to confirm full back-compat."""
    legacy_blob = {
        "id": "mem_v15",
        "project_name": "demo",
        "category": "decision",
        "content": "Use SQLite FTS5 for local memory search",
        "confidence": 0.9,
        "status": "accepted",
        "source": "manual",
        "created_at": "2026-04-23T00:00:00+00:00",
        "updated_at": "2026-04-23T00:00:00+00:00",
        "tags": ["search"],
        "compacted": False,
        "usage_count": 3,
        "last_accessed_at": "2026-05-01T12:00:00+00:00",
        "provenance": {"session_id": "sess_1"},
    }
    entry = MemoryEntry.from_dict(legacy_blob)
    assert entry.memory_type == "semantic"
    assert entry.usage_count == 3
    assert entry.last_accessed_at == datetime(
        2026, 5, 1, 12, 0, tzinfo=timezone.utc
    )
    # Round trip: re-serialize and reload — derivation should be stable.
    rebuilt = MemoryEntry.from_dict(entry.to_dict())
    assert rebuilt == entry


# ---------------------------------------------------------------------------
# Procedural type accepted on input but never auto-derived
# ---------------------------------------------------------------------------


def test_procedural_accepted_when_explicitly_set() -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="step1; step2; step3",
        source="manual",
        memory_type="procedural",
    )
    assert entry.memory_type == "procedural"


def test_derive_never_returns_procedural() -> None:
    """Sweep all categories — derivation never produces procedural."""
    sample_categories = [
        "architecture", "convention", "api", "bug", "decision",
        "raw_note", "", "unknown_category", "skill", "procedure",
    ]
    for category in sample_categories:
        entry = MemoryEntry.from_dict({
            "project_name": "demo",
            "category": category,
            "content": "x",
            "source": "obs_1",
        })
        assert entry.memory_type != "procedural", (
            f"category={category!r} unexpectedly derived to procedural"
        )


# ---------------------------------------------------------------------------
# MemoryType alias is exported and usable
# ---------------------------------------------------------------------------


def test_memory_type_alias_is_exported() -> None:
    """Smoke check: the alias is importable and matches the literal set."""
    valid_values = {"episodic", "semantic", "procedural"}
    # MemoryType is a Literal alias; we can only check usage at runtime by
    # constructing entries with each value.
    for value in valid_values:
        entry = MemoryEntry(
            project_name="demo",
            category="decision",
            content="x",
            source="manual",
            memory_type=value,  # type: ignore[arg-type]
        )
        assert entry.memory_type == value
    # Confirm the alias name itself is accessible.
    assert MemoryType is not None
