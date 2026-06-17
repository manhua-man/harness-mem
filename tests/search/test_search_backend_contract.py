from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.search.backend import SearchFilters, SQLiteSearchBackend
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


async def _seed(backend: LocalMemoryBackend) -> None:
    timestamp = datetime(2026, 6, 12, tzinfo=timezone.utc)
    await backend.verbatim_store.save(
        Observation(
            id="obs-search-backend",
            session_id="session-search-backend",
            client="pytest",
            raw_content="SearchBackend returns auditable storage v2 evidence.",
            content_type="transcript",
            timestamp=timestamp,
            metadata={"project_name": "demo", "corpus_id": "sessions"},
        )
    )
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-hot",
            project_name="demo",
            category="decision",
            content="SearchBackend wraps SQLite FTS for storage v2.",
            confidence=0.9,
            source="obs-search-backend",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-cold",
            project_name="demo",
            category="decision",
            content="Cold archive storage v2 SearchBackend recall.",
            confidence=0.8,
            source="obs-search-backend",
            created_at=timestamp,
            updated_at=timestamp,
            tier="archive",
        )
    )


def test_sqlite_search_backend_returns_unified_contract(backend: LocalMemoryBackend) -> None:
    run(_seed(backend))

    response = run(
        SQLiteSearchBackend(backend).search(
            "storage v2 SearchBackend",
            filters=SearchFilters(project_name="demo"),
            mode="fts",
            limit=3,
            budget_tokens=100,
        )
    )

    payload = response.to_dict()
    assert payload["fallback_metadata"]["backend"] == "sqlite"
    assert payload["requested_mode"] == "fts"
    assert payload["budget"]["requested_tokens"] == 100
    assert payload["source_coverage"]["memory_entry"] >= 1
    assert payload["drilldown_hints"]
    assert "mem-hot" in {result.source_id for result in response.results}
    assert "mem-cold" not in {result.source_id for result in response.results}


def test_sqlite_search_backend_deep_recall_includes_archive_tier(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))

    response = run(
        SQLiteSearchBackend(backend).search(
            "archive storage v2",
            filters=SearchFilters(project_name="demo", deep_recall=True),
            mode="fts",
            limit=5,
        )
    )

    assert "mem-cold" in {result.source_id for result in response.results}


def test_sqlite_search_backend_explains_context_outcome_ranking_hint(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))
    now = datetime.now(timezone.utc)
    run(
        LocalProjectProfileStore(backend.data_dir).save(
            ProjectProfile(project_name="demo", weak_link_signals=True)
        )
    )
    run(
        backend.structured_store.save_retrieval_signal(
            RetrievalSignal(
                project_name="demo",
                signal_type="context_outcome",
                target_kind="context_source",
                target_id="mem-hot",
                value=1.0,
                context={
                    "surface": "search_memory",
                    "outcome": "used",
                    "reason": "helped answer storage question",
                },
                recorded_at=now - timedelta(hours=1),
            )
        )
    )

    response = run(
        SQLiteSearchBackend(backend).search(
            "storage v2 SearchBackend",
            filters=SearchFilters(project_name="demo"),
            mode="fts",
            limit=3,
        )
    )

    result = next(item for item in response.results if item.source_id == "mem-hot")
    assert result.metadata["context_outcome_counts"]["used"] == 1
    assert result.metadata["context_outcome_score"] == 0.08
    assert result.metadata["last_context_outcome_at"] is not None
    assert result.metadata["ranking_explanation"][0]["kind"] == "context_outcome"


def test_sqlite_search_backend_outcome_hint_disabled_by_default(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))
    run(
        backend.structured_store.save_retrieval_signal(
            RetrievalSignal(
                project_name="demo",
                signal_type="context_outcome",
                target_kind="context_source",
                target_id="mem-hot",
                value=1.0,
                context={"surface": "search_memory", "outcome": "used"},
                recorded_at=datetime.now(timezone.utc),
            )
        )
    )

    response = run(
        SQLiteSearchBackend(backend).search(
            "storage v2 SearchBackend",
            filters=SearchFilters(project_name="demo"),
            mode="fts",
            limit=3,
        )
    )

    result = next(item for item in response.results if item.source_id == "mem-hot")
    assert result.metadata["context_outcome_counts"] == {}
    assert result.metadata["context_outcome_score"] == 0.0
    assert result.metadata["ranking_explanation"] == []
