"""Small deterministic causal-recall benchmark for harness-mem.

The benchmark seeds a semantic distractor plus a two-hop causal chain, then
checks whether typed relation traversal recovers the gold root cause. It is a
local smoke benchmark, not a broad retrieval-quality claim.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.read_api import search_memory, trace_relation_paths
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


BENCHMARK_PROJECT = "harness_mem_causal_benchmark"


async def _run_benchmark(data_dir: Path, project_name: str) -> dict[str, Any]:
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
        top_search_id = entries[0].id if entries else ""
        root_cause_correct = root_entity == "redis_pool_exhaustion"
        edge_recall = len(gold_edges.intersection(traversed_edges)) / len(gold_edges)
        return {
            "schema_version": "harness_mem.causal_benchmark.v1",
            "project_name": project_name,
            "query": "why API 500 errors happened",
            "top_search_memory_id": top_search_id,
            "semantic_distractor_ranked": top_search_id == "bench-distractor",
            "top_trace_root_entity": root_entity,
            "root_cause_correct": root_cause_correct,
            "edge_recall": edge_recall,
            "distractor_survived": root_cause_correct and "bench-distractor" in [entry.id for entry in entries],
            "path_count": len(paths),
            "top_path_score": top_path.score if top_path else 0.0,
            "paths": [
                {
                    "entities": path.entities,
                    "score": path.score,
                    "edge_ids": [fact.id for fact in path.facts],
                }
                for path in paths
            ],
            "passed": root_cause_correct and edge_recall == 1.0,
        }
    finally:
        await backend.close()


def run_causal_benchmark(
    *,
    data_dir: Path | None = None,
    project_name: str = BENCHMARK_PROJECT,
) -> dict[str, Any]:
    """Run the benchmark and return JSON-serializable metrics."""

    return asyncio.run(arun_causal_benchmark(data_dir=data_dir, project_name=project_name))


async def arun_causal_benchmark(
    *,
    data_dir: Path | None = None,
    project_name: str = BENCHMARK_PROJECT,
) -> dict[str, Any]:
    """Async benchmark entry point for CLI/MCP handlers."""

    with temporarily_disable_embeddings():
        if data_dir is not None:
            return await _run_benchmark(Path(data_dir), project_name)
        with TemporaryDirectory(prefix="harness-mem-causal-benchmark-") as tmp:
            return await _run_benchmark(Path(tmp), project_name)


__all__ = ["BENCHMARK_PROJECT", "arun_causal_benchmark", "run_causal_benchmark"]
