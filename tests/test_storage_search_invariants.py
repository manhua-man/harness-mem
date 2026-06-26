from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.read_api import (
    search_memory as read_search_memory,
    search_relation_facts as read_search_relation_facts,
)
from harness_mem.search.backend import (
    SearchFilters,
    SearchFacade,
    SQLiteSearchBackend,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


async def _new_backend(data_dir: Path) -> LocalMemoryBackend:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    return backend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = _run(_new_backend(tmp_path))
    try:
        yield backend
    finally:
        _run(backend.close())


def _ids(items: list[object]) -> set[str]:
    return {str(getattr(item, "id")) for item in items}


def _result_projects(response) -> set[str]:
    projects: set[str] = set()
    for result in response.results:
        project_name = result.metadata.get("project_name")
        if isinstance(project_name, str):
            projects.add(project_name)
    return projects


def test_canonical_truth_survives_missing_index_and_rebuilds_on_boot(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="canonicalrebuildtoken keeps canonical truth independent of the index",
        source="test",
        status="accepted",
    )
    entry_id = _run(backend.structured_store.save_memory_entry(entry))

    assert backend.structured_store.index.get("memory_entries", entry_id) is not None
    before, _ = _run(
        read_search_memory(
            backend,
            project_name="demo",
            query="canonicalrebuildtoken",
            record_signals=False,
        )
    )
    assert _ids(before) == {entry_id}

    assert backend.structured_store.index.delete("memory_entries", entry_id) is True
    assert backend.structured_store.index.get("memory_entries", entry_id) is None

    reloaded = _run(backend.structured_store.get_memory_entry(entry_id))
    assert reloaded is not None
    assert reloaded.content == entry.content
    assert reloaded.status == "accepted"

    missing_index, _ = _run(
        read_search_memory(
            backend,
            project_name="demo",
            query="canonicalrebuildtoken",
            record_signals=False,
        )
    )
    assert missing_index == []

    data_dir = backend.data_dir
    _run(backend.close())
    rebuilt = _run(_new_backend(data_dir))
    try:
        assert rebuilt.structured_store.index.get("memory_entries", entry_id) is not None
        restored, _ = _run(
            read_search_memory(
                rebuilt,
                project_name="demo",
                query="canonicalrebuildtoken",
                record_signals=False,
            )
        )
        assert _ids(restored) == {entry_id}
    finally:
        _run(rebuilt.close())


def test_vector_disabled_hybrid_search_falls_back_to_fts(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="vectorfallbacktoken must remain searchable without embeddings",
        source="test",
        status="accepted",
    )
    entry_id = _run(backend.structured_store.save_memory_entry(entry))

    response = _run(
        SQLiteSearchBackend(backend).search(
            "vectorfallbacktoken",
            filters=SearchFilters(project_name="demo"),
            mode="hybrid",
            limit=5,
        )
    )

    assert response.requested_mode == "hybrid"
    assert response.effective_mode == "fts"
    assert response.fallback_metadata["fallback_reason"] == "embedding not available"
    assert [result.source_id for result in response.results] == [entry_id]
    assert response.results[0].metadata["search_mode"] == "fts"


def test_search_facade_preserves_memory_relation_observation_semantics(backend) -> None:
    memory = MemoryEntry(
        project_name="demo",
        category="decision",
        content="semanticstoken memory entry preserves source and status",
        source="session:memory",
        status="accepted",
        memory_type="semantic",
    )
    relation = RelationFact(
        project_name="demo",
        source_entity="semanticstoken-service",
        target_entity="derived-index",
        relation_type="depends_on",
        evidence="semanticstoken relation evidence stays attached",
        source="session:relation",
        confidence=0.91,
        status="accepted",
    )
    observation = Observation(
        session_id="session-observation",
        client="codex",
        raw_content="semanticstoken observation keeps session and project metadata",
        content_type="turn",
        metadata={"project_name": "demo", "source": "session:observation"},
    )

    memory_id = _run(backend.structured_store.save_memory_entry(memory))
    relation_id = _run(backend.structured_store.save_relation_fact(relation))
    observation_id = _run(backend.verbatim_store.save(observation))

    facade = SearchFacade(backend)
    response = _run(
        facade.search(
            "semanticstoken",
            filters=SearchFilters(project_name="demo"),
            mode="auto",
            limit=10,
        )
    )
    results_by_kind = {result.source_kind: result for result in response.results}

    assert set(results_by_kind) == {"memory_entry", "relation_fact", "observation"}
    memory_result = results_by_kind["memory_entry"]
    assert memory_result.source_id == memory_id
    assert memory_result.metadata["project_name"] == "demo"
    assert memory_result.metadata["truth_status"] == "accepted"
    assert memory_result.metadata["memory_type"] == "semantic"
    assert memory_result.score is not None

    relation_result = results_by_kind["relation_fact"]
    assert relation_result.source_id == relation_id
    assert relation_result.metadata["project_name"] == "demo"
    assert relation_result.metadata["truth_status"] == "accepted"
    assert "semanticstoken-service depends_on derived-index" in relation_result.preview
    assert relation_result.score is not None

    observation_result = results_by_kind["observation"]
    assert observation_result.source_id == observation_id
    assert observation_result.metadata["project_name"] == "demo"
    assert observation_result.metadata["truth_status"] == "raw"
    assert observation_result.score is not None

    hydrated = _run(facade.hydrate(response))
    assert hydrated["memory_entry"][0].source == "session:memory"
    assert hydrated["memory_entry"][0].status == "accepted"
    assert hydrated["relation_fact"][0].evidence == relation.evidence
    assert hydrated["relation_fact"][0].source == "session:relation"
    assert hydrated["observation"][0].session_id == "session-observation"
    assert hydrated["observation"][0].metadata["project_name"] == "demo"

    entries, observations = _run(
        read_search_memory(
            backend,
            project_name="demo",
            query="semanticstoken",
            record_signals=False,
        )
    )
    relation_facts = _run(
        read_search_relation_facts(
            backend,
            project_name="demo",
            query="semanticstoken",
        )
    )
    assert _ids(entries) == {memory_id}
    assert _ids(observations) == {observation_id}
    assert _ids(relation_facts) == {relation_id}


def test_project_scope_filters_results_and_scope_all_keeps_project_identity(backend) -> None:
    for project in ("alpha", "beta"):
        _run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name=project,
                    category="decision",
                    content=f"isolationtoken memory for {project}",
                    source="test",
                    status="accepted",
                )
            )
        )
        _run(
            backend.structured_store.save_relation_fact(
                RelationFact(
                    project_name=project,
                    source_entity=f"isolationtoken-{project}",
                    target_entity="search",
                    relation_type="touches",
                    evidence=f"isolationtoken relation for {project}",
                    source="test",
                    status="accepted",
                )
            )
        )
        _run(
            backend.verbatim_store.save(
                Observation(
                    session_id=f"session-{project}",
                    client="codex",
                    raw_content=f"isolationtoken observation for {project}",
                    content_type="turn",
                    metadata={"project_name": project},
                )
            )
        )

    project_response = _run(
        SQLiteSearchBackend(backend).search(
            "isolationtoken",
            filters=SearchFilters(project_name="alpha", scope="project"),
            mode="auto",
            limit=10,
        )
    )
    assert project_response.results
    assert _result_projects(project_response) == {"alpha"}
    assert project_response.source_coverage == {
        "memory_entry": 1,
        "relation_fact": 1,
        "observation": 1,
    }

    all_response = _run(
        SQLiteSearchBackend(backend).search(
            "isolationtoken",
            filters=SearchFilters(scope="all"),
            mode="auto",
            limit=10,
        )
    )
    assert _result_projects(all_response) == {"alpha", "beta"}
    assert all_response.source_coverage == {
        "memory_entry": 2,
        "relation_fact": 2,
        "observation": 2,
    }


def test_pending_and_rejected_truth_do_not_appear_as_confirmed_search_results(
    backend,
) -> None:
    to_confirm = MemoryEntry(
        project_name="demo",
        category="decision",
        content="reviewvisibilitytoken confirmed memory",
        source="test",
        status="pending",
    )
    still_pending = MemoryEntry(
        project_name="demo",
        category="decision",
        content="reviewvisibilitytoken pending memory",
        source="test",
        status="pending",
    )
    to_reject = MemoryEntry(
        project_name="demo",
        category="decision",
        content="reviewvisibilitytoken rejected memory",
        source="test",
        status="pending",
    )
    confirmed_memory_id = _run(backend.structured_store.save_memory_entry(to_confirm))
    pending_memory_id = _run(backend.structured_store.save_memory_entry(still_pending))
    rejected_memory_id = _run(backend.structured_store.save_memory_entry(to_reject))
    assert _run(
        backend.structured_store.update_memory_entry_status(
            confirmed_memory_id,
            "accepted",
        )
    )
    assert _run(
        backend.structured_store.update_memory_entry_status(
            rejected_memory_id,
            "rejected",
        )
    )

    relation_to_confirm = RelationFact(
        project_name="demo",
        source_entity="reviewvisibilitytoken-confirmed",
        target_entity="search",
        relation_type="supports",
        evidence="reviewvisibilitytoken confirmed relation",
        source="test",
        status="pending",
    )
    relation_still_pending = RelationFact(
        project_name="demo",
        source_entity="reviewvisibilitytoken-pending",
        target_entity="search",
        relation_type="supports",
        evidence="reviewvisibilitytoken pending relation",
        source="test",
        status="pending",
    )
    relation_to_reject = RelationFact(
        project_name="demo",
        source_entity="reviewvisibilitytoken-rejected",
        target_entity="search",
        relation_type="supports",
        evidence="reviewvisibilitytoken rejected relation",
        source="test",
        status="pending",
    )
    confirmed_relation_id = _run(
        backend.structured_store.save_relation_fact(relation_to_confirm)
    )
    pending_relation_id = _run(
        backend.structured_store.save_relation_fact(relation_still_pending)
    )
    rejected_relation_id = _run(
        backend.structured_store.save_relation_fact(relation_to_reject)
    )
    assert _run(
        backend.structured_store.update_relation_fact_status(
            confirmed_relation_id,
            "accepted",
        )
    )
    assert _run(
        backend.structured_store.update_relation_fact_status(
            rejected_relation_id,
            "rejected",
        )
    )

    response = _run(
        SQLiteSearchBackend(backend).search(
            "reviewvisibilitytoken",
            filters=SearchFilters(project_name="demo"),
            mode="auto",
            limit=10,
        )
    )
    ids_by_kind: dict[str, set[str]] = {}
    for result in response.results:
        ids_by_kind.setdefault(result.source_kind, set()).add(result.source_id)

    assert ids_by_kind["memory_entry"] == {confirmed_memory_id}
    assert ids_by_kind["relation_fact"] == {confirmed_relation_id}
    assert pending_memory_id not in ids_by_kind["memory_entry"]
    assert rejected_memory_id not in ids_by_kind["memory_entry"]
    assert pending_relation_id not in ids_by_kind["relation_fact"]
    assert rejected_relation_id not in ids_by_kind["relation_fact"]

    assert backend.structured_store.index.get(
        "memory_entries",
        confirmed_memory_id,
    )["status"] == "accepted"
    assert backend.structured_store.index.get(
        "memory_entries",
        rejected_memory_id,
    )["status"] == "rejected"
    assert backend.structured_store.index.get(
        "relation_facts",
        confirmed_relation_id,
    )["status"] == "accepted"
    assert backend.structured_store.index.get(
        "relation_facts",
        rejected_relation_id,
    )["status"] == "rejected"
