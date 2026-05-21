from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import MemoryEntry, Observation, RelationFact
from harness_mem.read_api import parse_relative_time_window, trace_relation_paths
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.storage


def test_parse_relative_time_window_two_months_ago():
    parsed = parse_relative_time_window(
        "two months ago API route decision",
        now=datetime(2026, 5, 21, 12, tzinfo=timezone.utc),
    )

    assert parsed.query == "API route decision"
    assert parsed.phrase == "two months ago"
    assert parsed.start == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert parsed.end == datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_time_window_filters_observations_and_structured_truth(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        march = datetime(2026, 3, 15, tzinfo=timezone.utc)
        may = datetime(2026, 5, 15, tzinfo=timezone.utc)
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-march",
                    session_id="sess-march",
                    client="codex",
                    raw_content="API route decision sentinel",
                    content_type="transcript",
                    timestamp=march,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-may",
                    session_id="sess-may",
                    client="codex",
                    raw_content="API route decision sentinel",
                    content_type="transcript",
                    timestamp=may,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id="entry-march",
                    project_name="demo",
                    category="decision",
                    content="API route decision sentinel",
                    source="manual",
                    created_at=march,
                    updated_at=march,
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id="entry-may",
                    project_name="demo",
                    category="decision",
                    content="API route decision sentinel",
                    source="manual",
                    created_at=may,
                    updated_at=may,
                )
            )
        )

        parsed = parse_relative_time_window(
            "two months ago API route decision sentinel",
            now=datetime(2026, 5, 21, 12, tzinfo=timezone.utc),
        )
        observations = run(
            backend.verbatim_store.search(
                parsed.query,
                project_name="demo",
                mode="fts",
                limit=10,
                time_window=parsed.time_window,
            )
        )
        entries = run(
            backend.structured_store.search_memory_entries(
                parsed.query,
                "demo",
                mode="fts",
                limit=10,
                time_window=parsed.time_window,
            )
        )

        assert [observation.id for observation in observations] == ["obs-march"]
        assert [entry.id for entry in entries] == ["entry-march"]
    finally:
        run(backend.close())


def test_trace_relation_paths_bounded_current_only(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_relation_fact(
                RelationFact(
                    id="fact-a-b",
                    project_name="demo",
                    source_entity="A",
                    target_entity="B",
                    relation_type="depends_on",
                    evidence="A depends on B.",
                    source="manual",
                    confidence=0.9,
                )
            )
        )
        run(
            backend.structured_store.save_relation_fact(
                RelationFact(
                    id="fact-b-c",
                    project_name="demo",
                    source_entity="B",
                    target_entity="C",
                    relation_type="depends_on",
                    evidence="B depends on C.",
                    source="manual",
                    confidence=0.8,
                )
            )
        )
        run(
            backend.structured_store.save_relation_fact(
                RelationFact(
                    id="fact-stale",
                    project_name="demo",
                    source_entity="A",
                    target_entity="Legacy",
                    relation_type="depends_on",
                    evidence="A used to depend on Legacy.",
                    source="manual",
                    valid_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    confidence=0.95,
                )
            )
        )

        paths = run(
            trace_relation_paths(
                backend,
                project_name="demo",
                source_entity="A",
                relation_type="depends_on",
                max_depth=2,
                limit=10,
            )
        )

        assert [path.entities for path in paths] == [["A", "B"], ["A", "B", "C"]]
        assert all("Legacy" not in path.entities for path in paths)

        with pytest.raises(ValueError, match="max_depth must be <= 3"):
            run(
                trace_relation_paths(
                    backend,
                    project_name="demo",
                    source_entity="A",
                    max_depth=4,
                )
            )
    finally:
        run(backend.close())
