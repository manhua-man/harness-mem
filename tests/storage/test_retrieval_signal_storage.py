from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import RetrievalSignal
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

pytestmark = pytest.mark.storage


@pytest.fixture
def store(tmp_path: Path):
    local_store = LocalStructuredStore(tmp_path)
    try:
        yield local_store
    finally:
        local_store.close()


def test_retrieval_signal_schema_roundtrip():
    """to_dict / from_dict round-trips field values."""
    recorded = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    original = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-001",
        recorded_at=recorded,
        value=0.87,
        context={"session_id": "sess-1", "query": "fts5"},
    )

    rebuilt = RetrievalSignal.from_dict(original.to_dict())

    assert rebuilt.id == original.id
    assert rebuilt.project_name == "demo"
    assert rebuilt.signal_type == "search_hit"
    assert rebuilt.target_kind == "memory_entry"
    assert rebuilt.target_id == "entry-001"
    assert rebuilt.recorded_at == recorded
    assert rebuilt.value == pytest.approx(0.87)
    assert rebuilt.context == {"session_id": "sess-1", "query": "fts5"}


def test_retrieval_signal_from_dict_defends_against_missing_fields():
    """Older blobs missing optional fields still load with sensible defaults."""
    minimal = {
        "id": "sig-001",
        "project_name": "demo",
        "signal_type": "wake_surfaced",
        "target_kind": "rule",
        "target_id": "rule-001",
        "recorded_at": "2026-05-17T12:00:00+00:00",
    }

    rebuilt = RetrievalSignal.from_dict(dict(minimal))

    assert rebuilt.id == "sig-001"
    assert rebuilt.value is None
    assert rebuilt.context is None


def test_retrieval_signal_storage_roundtrip(store: LocalStructuredStore):
    signal = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-001",
        value=0.42,
    )

    assert run(store.save_retrieval_signal(signal)) == signal.id

    listed = run(store.query_retrieval_signals("demo"))
    assert [item.id for item in listed] == [signal.id]
    assert listed[0].value == pytest.approx(0.42)


def test_retrieval_signal_filters(store: LocalStructuredStore):
    """signal_type / target_kind / target_id filters return only matches."""
    base = datetime.now(timezone.utc)
    hit = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-001",
        recorded_at=base - timedelta(minutes=3),
    )
    surfaced = RetrievalSignal(
        project_name="demo",
        signal_type="wake_surfaced",
        target_kind="memory_entry",
        target_id="entry-002",
        recorded_at=base - timedelta(minutes=2),
    )
    other_kind = RetrievalSignal(
        project_name="demo",
        signal_type="wake_surfaced",
        target_kind="rule",
        target_id="rule-001",
        recorded_at=base - timedelta(minutes=1),
    )

    for sig in (hit, surfaced, other_kind):
        run(store.save_retrieval_signal(sig))

    by_type = run(store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert [item.id for item in by_type] == [hit.id]

    by_kind = run(store.query_retrieval_signals("demo", target_kind="rule"))
    assert [item.id for item in by_kind] == [other_kind.id]

    by_target_id = run(store.query_retrieval_signals("demo", target_id="entry-002"))
    assert [item.id for item in by_target_id] == [surfaced.id]


def test_retrieval_signal_since_filter(store: LocalStructuredStore):
    """`since=` returns only signals at or after the given timestamp."""
    base = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    older = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-001",
        recorded_at=base - timedelta(hours=2),
    )
    middle = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-002",
        recorded_at=base - timedelta(hours=1),
    )
    newer = RetrievalSignal(
        project_name="demo",
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="entry-003",
        recorded_at=base,
    )

    for sig in (older, middle, newer):
        run(store.save_retrieval_signal(sig))

    since_middle = run(
        store.query_retrieval_signals("demo", since=middle.recorded_at)
    )
    assert {item.id for item in since_middle} == {middle.id, newer.id}
    # Newest first.
    assert since_middle[0].id == newer.id


def test_retrieval_signal_empty_project_returns_empty_list(store: LocalStructuredStore):
    assert run(store.query_retrieval_signals("nobody")) == []
