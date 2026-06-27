from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from harness_mem.core.schemas.recall_result import (
    RecallEvidence,
    RecallResult,
    RecallStep,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.embedding import embeddings_disabled, temporarily_disable_embeddings
from harness_mem.event_log import (
    StateEventType,
    append_state_event,
    iter_state_events,
    replay_state_events,
    state_audit_summary,
)
from harness_mem.relation_scoring import (
    relation_family,
    score_relation_fact,
    score_relation_path,
)
from harness_mem.read_api import search_memory, trace_relation_paths
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


BENCHMARK_PROJECT = "harness_mem_causal_benchmark"


async def _run_causal_benchmark(data_dir: Path, project_name: str) -> dict:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        root_entry = MemoryEntry(
            id="bench-root-cause",
            project_name=project_name,
            category="bug",
            content="Redis connection pool exhaustion was the root cause of the retry storm.",
            confidence=0.95,
            source="benchmark:gold",
            status="accepted",
            tags=["benchmark", "root_cause"],
        )
        distractor = MemoryEntry(
            id="bench-distractor",
            project_name=project_name,
            category="bug",
            content="API 500 errors runbook: restart web workers and inspect generic logs.",
            confidence=0.9,
            source="benchmark:distractor",
            status="accepted",
            tags=["benchmark", "semantic_distractor"],
        )
        await backend.structured_store.save_memory_entry(root_entry)
        await backend.structured_store.save_memory_entry(distractor)
        facts = [
            RelationFact(
                id="bench-edge-api-retries",
                project_name=project_name,
                source_entity="api_500_incident",
                target_entity="retry_storm",
                relation_type="caused_by",
                confidence=0.95,
                evidence="The API 500 incident was caused by a retry storm.",
                source="benchmark:gold",
                status="accepted",
                tags=["benchmark"],
            ),
            RelationFact(
                id="bench-edge-retries-redis",
                project_name=project_name,
                source_entity="retry_storm",
                target_entity="redis_pool_exhaustion",
                relation_type="caused_by",
                confidence=0.95,
                evidence="The retry storm was caused by Redis pool exhaustion.",
                source="benchmark:gold",
                status="accepted",
                tags=["benchmark"],
            ),
        ]
        for fact in facts:
            await backend.structured_store.save_relation_fact(fact)

        entries, _ = await search_memory(
            backend,
            project_name=project_name,
            query="why API 500 errors happened",
            scope="project",
            mode="fts",
            memory_entry_limit=5,
            observation_limit=0,
            record_signals=False,
        )
        paths = await trace_relation_paths(
            backend,
            project_name=project_name,
            source_entity="api_500_incident",
            max_depth=2,
            limit=5,
        )

        top_path = paths[0] if paths else None
        root_entity = top_path.entities[-1] if top_path and top_path.entities else ""
        gold_edges = {"bench-edge-api-retries", "bench-edge-retries-redis"}
        traversed_edges = {fact.id for path in paths for fact in path.facts}
        root_cause_correct = root_entity == "redis_pool_exhaustion"
        edge_recall = len(gold_edges.intersection(traversed_edges)) / len(gold_edges)
        return {
            "root_cause_correct": root_cause_correct,
            "edge_recall": edge_recall,
            "path_count": len(paths),
            "passed": root_cause_correct and edge_recall == 1.0,
        }
    finally:
        await backend.close()


def run_causal_benchmark() -> dict:
    return asyncio.run(arun_causal_benchmark())


async def arun_causal_benchmark() -> dict:
    with temporarily_disable_embeddings():
        with TemporaryDirectory(prefix="harness-mem-causal-benchmark-") as tmp:
            return await _run_causal_benchmark(Path(tmp), BENCHMARK_PROJECT)


def test_recall_result_round_trip() -> None:
    result = RecallResult(
        why="selected by search",
        evidence=[
            RecallEvidence(
                source_id="mem-1",
                source_kind="memory_entry",
                content_excerpt="Use pgvector.",
                score=0.9,
                reason="search_memory:memory_entry",
            )
        ],
        steps=[
            RecallStep(
                tier="search",
                query="vector backend",
                status="ok",
                result_count=1,
            )
        ],
        status="partial",
        tier_path=["search"],
    )

    hydrated = RecallResult.from_dict(result.to_dict())

    assert hydrated.to_dict() == result.to_dict()
    assert hydrated.schema_version == "harness_mem.recall_result.v1"
    assert hydrated.contract == "harness_mem.recall_result"


def test_relation_scoring_prefers_causal_edges() -> None:
    causal = RelationFact(
        project_name="p",
        source_entity="incident",
        target_entity="root",
        relation_type="caused_by",
        evidence="root cause",
        source="manual",
        confidence=0.8,
    )
    generic = RelationFact(
        project_name="p",
        source_entity="incident",
        target_entity="runbook",
        relation_type="associated_with",
        evidence="similar words",
        source="heuristic",
        confidence=0.8,
    )

    assert relation_family(causal.relation_type) == "causal"
    assert score_relation_fact(causal) > score_relation_fact(generic)
    assert score_relation_path((causal, generic)) < score_relation_fact(causal)


def test_state_event_log_filters_and_summarizes(tmp_path: Path) -> None:
    event_id = append_state_event(
        tmp_path,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name="demo",
        target_kind="memory_entry",
        target_id="mem-1",
        status="pending",
        source_surface="test",
        actor="pytest",
        payload={"category": "decision"},
    )
    append_state_event(
        tmp_path,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name="other",
        target_kind="memory_entry",
        target_id="mem-2",
        status="accepted",
        source_surface="test",
    )
    (tmp_path / "state-events.log").write_text(
        (tmp_path / "state-events.log").read_text(encoding="utf-8")
        + "{not-json}\n",
        encoding="utf-8",
    )

    events = list(iter_state_events(tmp_path, project_name="demo"))
    summary = state_audit_summary(tmp_path, project_name="demo")
    replay = replay_state_events(tmp_path, project_name="demo")

    assert events[0]["id"] == event_id
    assert len(events) == 1
    assert summary["event_count"] == 1
    assert summary["by_type"]["candidate_created"] == 1
    assert replay["targets"]["memory_entry:mem-1"]["latest_status"] == "pending"


def test_state_event_reads_do_not_create_missing_ledger_parent(tmp_path: Path) -> None:
    data_dir = tmp_path / "missing" / "data"

    summary = state_audit_summary(data_dir, project_name="demo")
    replay = replay_state_events(data_dir, project_name="demo")

    assert summary["event_count"] == 0
    assert replay["target_count"] == 0
    assert not data_dir.exists()


def test_causal_benchmark_passes() -> None:
    result = run_causal_benchmark()

    assert result["passed"] is True
    assert result["root_cause_correct"] is True
    assert result["edge_recall"] == 1.0


def test_causal_benchmark_does_not_mutate_embedding_env(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    observed_values: list[str | None] = []

    async def watch_env() -> None:
        for _ in range(20):
            observed_values.append(os.environ.get("HARNESS_MEM_DISABLE_EMBEDDINGS"))
            await asyncio.sleep(0)

    async def run_with_watcher() -> dict:
        result, _ = await asyncio.gather(arun_causal_benchmark(), watch_env())
        return result

    result = asyncio.run(run_with_watcher())

    assert result["passed"] is True
    assert observed_values
    assert all(value is None for value in observed_values)
    assert os.environ.get("HARNESS_MEM_DISABLE_EMBEDDINGS") is None


def test_temporary_disable_embeddings_is_context_local(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)

    assert embeddings_disabled() is False
    with temporarily_disable_embeddings():
        assert embeddings_disabled() is True
        assert os.environ.get("HARNESS_MEM_DISABLE_EMBEDDINGS") is None
    assert embeddings_disabled() is False
