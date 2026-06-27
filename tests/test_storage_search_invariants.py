from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
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
from harness_mem.storage import CandidateStore, DerivedIndex, TruthStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.reflection_job_store import ReflectionJobStore


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_structured_store_keeps_truth_and_candidate_boundaries(backend) -> None:
    assert isinstance(backend.structured_store.truth_store, TruthStore)
    assert isinstance(backend.structured_store.candidate_store, CandidateStore)


def test_reflection_jobs_use_public_derived_index_boundary(backend) -> None:
    assert isinstance(backend.structured_store.index, DerivedIndex)
    assert isinstance(backend.reflection_job_store, ReflectionJobStore)

    repo_root = Path(__file__).resolve().parents[1]
    forbidden_private_index_access = (
        "structured_store._index",
        "_structured_store._index",
        "verbatim_store._index",
        "_verbatim_store._index",
    )
    offenders: list[str] = []
    for path in (repo_root / "harness_mem").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_private_index_access:
            if pattern in text:
                offenders.append(f"{path.relative_to(repo_root)}:{pattern}")

    assert offenders == []


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


def test_canonical_boot_rebuilds_relation_rule_observation_indexes(backend) -> None:
    relation = RelationFact(
        project_name="demo",
        source_entity="canonicalboot-token",
        target_entity="search",
        relation_type="protects",
        evidence="canonicalboot-token relation rebuild evidence",
        source="test",
        status="accepted",
    )
    rule = ConfirmedRule(
        project_name="demo",
        pattern="canonicalboot-token rule rebuilds from canonical truth",
        trigger="search invariant test",
        source_candidate_id="rule-candidate-1",
    )
    observation = Observation(
        session_id="session-canonicalboot",
        client="codex",
        raw_content="canonicalboot-token observation rebuilds trigram postings",
        content_type="turn",
        metadata={"project_name": "demo"},
    )

    relation_id = _run(backend.structured_store.save_relation_fact(relation))
    rule_id = _run(backend.structured_store.save_confirmed_rule(rule))
    observation_id = _run(backend.verbatim_store.save(observation))

    assert backend.structured_store.index.delete("relation_facts", relation_id) is True
    assert backend.structured_store.index.delete("confirmed_rules", rule_id) is True
    assert backend.verbatim_store.index.delete("observations", observation_id) is True
    backend.verbatim_store.index.delete_observation_trigrams(observation_id)

    data_dir = backend.data_dir
    _run(backend.close())
    rebuilt = _run(_new_backend(data_dir))
    try:
        assert rebuilt.structured_store.index.get("relation_facts", relation_id) is not None
        assert rebuilt.structured_store.index.get("confirmed_rules", rule_id) is not None
        assert rebuilt.verbatim_store.index.get("observations", observation_id) is not None

        relation_results = _run(
            read_search_relation_facts(
                rebuilt,
                project_name="demo",
                query="canonicalboot-token",
            )
        )
        rules = _run(rebuilt.structured_store.list_confirmed_rules("demo"))
        regex_matches = _run(
            rebuilt.verbatim_store.regex_search_observations(
                "canonicalboot-token",
                project_name="demo",
            )
        )

        assert _ids(relation_results) == {relation_id}
        assert _ids(rules) == {rule_id}
        assert {match.observation.id for match in regex_matches} == {observation_id}
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


def test_include_history_deep_recall_and_truth_status_control_historical_visibility(
    backend,
) -> None:
    past = _now() - timedelta(days=1)
    historical = MemoryEntry(
        project_name="demo",
        category="decision",
        content="historytoken superseded memory remains available only for history",
        source="test",
        status="accepted",
        valid_to=past,
    )
    current = MemoryEntry(
        project_name="demo",
        category="decision",
        content="historytoken current memory remains default-visible",
        source="test",
        status="accepted",
    )
    historical_id = _run(backend.structured_store.save_memory_entry(historical))
    current_id = _run(backend.structured_store.save_memory_entry(current))

    default_response = _run(
        SearchFacade(backend).search(
            "historytoken",
            filters=SearchFilters(project_name="demo"),
            limit=10,
        )
    )
    assert [result.source_id for result in default_response.results] == [current_id]

    history_response = _run(
        SearchFacade(backend).search(
            "historytoken",
            filters=SearchFilters(project_name="demo", include_history=True),
            limit=10,
        )
    )
    statuses = {
        result.source_id: result.metadata["truth_status"]
        for result in history_response.results
        if result.source_kind == "memory_entry"
    }
    assert statuses[current_id] == "accepted"
    assert statuses[historical_id] == "historical"

    deep_response = _run(
        SearchFacade(backend).search(
            "historytoken",
            filters=SearchFilters(project_name="demo", deep_recall=True),
            limit=10,
        )
    )
    assert {result.source_id for result in deep_response.results} == {
        current_id,
        historical_id,
    }


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


def test_read_api_per_type_limits_do_not_allow_memory_hits_to_starve_observations(
    backend,
) -> None:
    for idx in range(30):
        _run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content=f"starvationtoken memory result {idx}",
                    source="test",
                    status="accepted",
                )
            )
        )
    observation_id = _run(
        backend.verbatim_store.save(
            Observation(
                session_id="session-starvation",
                client="codex",
                raw_content="starvationtoken observation must survive source balancing",
                content_type="turn",
                metadata={"project_name": "demo"},
            )
        )
    )

    entries, observations = _run(
        read_search_memory(
            backend,
            project_name="demo",
            query="starvationtoken",
            memory_entry_limit=1,
            observation_limit=1,
            record_signals=False,
        )
    )

    assert len(entries) == 1
    assert _ids(observations) == {observation_id}


def test_soft_deleted_memory_and_observations_are_absent_from_search_and_regex(
    backend,
) -> None:
    memory_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="softdeletetoken memory should disappear",
                source="test",
                status="accepted",
            )
        )
    )
    observation_id = _run(
        backend.verbatim_store.save(
            Observation(
                session_id="session-soft-delete",
                client="codex",
                raw_content="softdeletetoken observation should disappear",
                content_type="turn",
                metadata={"project_name": "demo"},
            )
        )
    )

    assert _run(backend.structured_store.soft_delete_memory_entry(memory_id)) is True
    assert _run(backend.verbatim_store.soft_delete(observation_id)) is True

    entries, observations = _run(
        read_search_memory(
            backend,
            project_name="demo",
            query="softdeletetoken",
            record_signals=False,
        )
    )
    regex_matches = _run(
        backend.verbatim_store.regex_search_observations(
            "softdeletetoken",
            project_name="demo",
        )
    )

    assert entries == []
    assert observations == []
    assert regex_matches == []
