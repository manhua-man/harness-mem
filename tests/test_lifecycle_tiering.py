from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.lifecycle import (
    persist_lifecycle_tier_candidates,
    select_lifecycle_tier_candidates,
)
from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


async def _seed_entries(backend: LocalMemoryBackend) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-hot-tier",
            project_name="demo",
            category="decision",
            content="lifecycle search should find hot tier",
            confidence=0.8,
            source="unit",
            created_at=now,
            updated_at=now,
            tier="hot",
        )
    )
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-archive-tier",
            project_name="demo",
            category="decision",
            content="lifecycle search should require deep recall for archive tier",
            confidence=0.8,
            source="unit",
            created_at=now,
            updated_at=now,
            tier="archive",
        )
    )


def test_default_search_excludes_archive_and_deep_recall_includes_it(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed_entries(backend))

    entries, _ = run(
        search_memory(
            backend,
            project_name="demo",
            query="lifecycle search tier",
            mode="fts",
            record_signals=False,
        )
    )
    assert "mem-hot-tier" in {entry.id for entry in entries}
    assert "mem-archive-tier" not in {entry.id for entry in entries}

    deep_entries, _ = run(
        search_memory(
            backend,
            project_name="demo",
            query="lifecycle search tier",
            mode="fts",
            deep_recall=True,
            record_signals=False,
        )
    )
    assert "mem-archive-tier" in {entry.id for entry in deep_entries}


def test_lifecycle_candidates_are_proposals_not_truth_mutations() -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    old_entry = MemoryEntry(
        id="old-entry",
        project_name="demo",
        category="decision",
        content="old decision",
        confidence=0.8,
        source="unit",
        created_at=now - timedelta(days=200),
        updated_at=now - timedelta(days=200),
        tier="hot",
        decay_score=0.92,
    )

    candidates = select_lifecycle_tier_candidates([old_entry], now=now)

    assert len(candidates) == 1
    assert candidates[0].target_id == "old-entry"
    assert candidates[0].candidate_kind == "tier_downgrade"
    assert candidates[0].to_tier == "archive"
    assert old_entry.tier == "hot"


def test_lifecycle_candidates_persist_as_reviewable_candidates(
    backend: LocalMemoryBackend,
) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    old_entry = MemoryEntry(
        id="persisted-old-entry",
        project_name="demo",
        category="decision",
        content="old decision should be archived only through review",
        confidence=0.8,
        source="unit",
        created_at=now - timedelta(days=200),
        updated_at=now - timedelta(days=200),
        tier="hot",
        decay_score=0.92,
    )
    run(backend.structured_store.save_memory_entry(old_entry))
    candidates = select_lifecycle_tier_candidates([old_entry], now=now)

    saved_ids = run(
        persist_lifecycle_tier_candidates(
            backend.structured_store,
            candidates,
            project_name="demo",
            metabolism_run_id="tier-test",
        )
    )
    listed = run(
        backend.structured_store.list_stale_truth_suggestion_candidates(
            "demo",
            status="pending",
        )
    )
    stored = next(candidate for candidate in listed if candidate.id == saved_ids[0])

    assert stored.target_id == "persisted-old-entry"
    assert stored.model_extra["lifecycle_candidate_kind"] == "tier_downgrade"
    assert stored.model_extra["from_tier"] == "hot"
    assert stored.model_extra["to_tier"] == "archive"
    assert stored.model_extra["confidence"] == candidates[0].confidence
    unchanged = run(
        backend.structured_store.get_memory_entry("persisted-old-entry")
    )
    assert unchanged is not None
    assert unchanged.tier == "hot"
