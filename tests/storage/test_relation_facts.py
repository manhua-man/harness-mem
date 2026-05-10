from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import RelationFact
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


def test_relation_fact_roundtrip(store: LocalStructuredStore):
    fact = RelationFact(
        project_name="demo",
        source_entity="HybridSearchLayer",
        target_entity="SQLiteIndex",
        relation_type="uses",
        confidence=0.91,
        evidence="HybridSearchLayer delegates local FTS reads to SQLiteIndex.",
        source="manual",
        tags=["search"],
        provenance={"session_id": "session-001"},
    )

    assert run(store.save_relation_fact(fact)) == fact.id

    loaded = run(store.get_relation_fact(fact.id))
    assert loaded == fact
    assert loaded.provenance == {"session_id": "session-001"}


def test_relation_fact_list_filters_project_entity_and_type(store: LocalStructuredStore):
    older = RelationFact(
        project_name="demo",
        source_entity="cli",
        target_entity="LocalStructuredStore",
        relation_type="writes_to",
        evidence="CLI commands persist memory through LocalStructuredStore.",
        source="manual",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        updated_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    newer = RelationFact(
        project_name="demo",
        source_entity="cli",
        target_entity="SQLiteIndex",
        relation_type="indexes_to",
        evidence="CLI writes are mirrored into SQLiteIndex for search.",
        source="manual",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    other_project = RelationFact(
        project_name="other",
        source_entity="cli",
        target_entity="SQLiteIndex",
        relation_type="indexes_to",
        evidence="Other project relation should stay scoped out.",
        source="manual",
        created_at=datetime.now(timezone.utc) + timedelta(days=1),
        updated_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert run(store.save_relation_fact(older)) == older.id
    assert run(store.save_relation_fact(newer)) == newer.id
    assert run(store.save_relation_fact(other_project)) == other_project.id

    listed = run(store.list_relation_facts("demo", limit=10))
    assert [fact.id for fact in listed] == [newer.id, older.id]

    filtered = run(
        store.list_relation_facts(
            "demo",
            source_entity="cli",
            target_entity="SQLiteIndex",
            relation_type="indexes_to",
        )
    )
    assert [fact.id for fact in filtered] == [newer.id]


def test_relation_fact_search_uses_evidence_and_project_scope(store: LocalStructuredStore):
    matching = RelationFact(
        project_name="demo",
        source_entity="RelationFact",
        target_entity="SQLiteIndex",
        relation_type="indexed_by",
        evidence="Relation facts are searchable by distinctive keyword alphaomega.",
        source="manual",
    )
    other_project = RelationFact(
        project_name="other",
        source_entity="RelationFact",
        target_entity="SQLiteIndex",
        relation_type="indexed_by",
        evidence="Relation facts are searchable by distinctive keyword alphaomega.",
        source="manual",
    )

    assert run(store.save_relation_fact(matching)) == matching.id
    assert run(store.save_relation_fact(other_project)) == other_project.id

    results = run(store.search_relation_facts("alphaomega", project_name="demo"))
    assert [fact.id for fact in results] == [matching.id]

    assert run(store.search_relation_facts("   ", project_name="demo")) == []
