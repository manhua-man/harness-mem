from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any

import yaml

from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.read_api import search_memory, search_relation_facts
from harness_mem.search.retrieval_quality import build_golden_ab_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@dataclass(frozen=True)
class RetrievalQualityCase:
    id: str
    project_name: str
    query: str
    memory_entries: list[dict]
    observations: list[dict]
    relation_facts: list[dict]
    noise_memory_entries: list[dict]
    noise_observations: list[dict]
    noise_relation_facts: list[dict]
    search: dict[str, Any]
    expected: dict


def _load_cases(path: Path) -> list[RetrievalQualityCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_cases = [*payload["queries"], *_expand_generated_matrix(payload)]
    cases = [
        RetrievalQualityCase(
            id=item["id"],
            project_name=item["project_name"],
            query=item["query"],
            memory_entries=list(item.get("memory_entries", [])),
            observations=list(item.get("observations", [])),
            relation_facts=list(item.get("relation_facts", [])),
            noise_memory_entries=list(item.get("noise_memory_entries", [])),
            noise_observations=list(item.get("noise_observations", [])),
            noise_relation_facts=list(item.get("noise_relation_facts", [])),
            search=dict(item.get("search", {})),
            expected=dict(item["expected"]),
        )
        for item in raw_cases
    ]
    declared = int(payload.get("declared_case_count", len(cases)))
    if len(cases) != declared:
        raise ValueError(
            f"retrieval golden declares {declared} cases but expands to {len(cases)}"
        )
    return cases


def _expand_generated_matrix(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand compact deterministic surface-isolation cases from the golden spec."""

    matrix = dict(payload.get("generated_matrix") or {})
    generated: list[dict[str, Any]] = []
    for surface in ("memory", "observation", "relation"):
        for index in range(1, int(matrix.get(surface, 0)) + 1):
            suffix = f"{index:02d}"
            project = f"retrieval-matrix-{surface}-{suffix}"
            query = f"matrix {surface} isolated token {suffix}"
            item: dict[str, Any] = {
                "id": f"matrix_{surface}_{suffix}",
                "project_name": project,
                "query": query,
                "expected": {
                    "memory_entry_ids": [],
                    "observation_ids": [],
                    "relation_fact_ids": [],
                },
                "search": {
                    "scope": "project",
                    "mode": "fts",
                    "memory_entry_limit": 5,
                    "observation_limit": 5,
                    "relation_fact_limit": 5,
                },
            }
            entity_id = f"matrix-{surface}-{suffix}"
            if surface == "memory":
                item["memory_entries"] = [
                    {
                        "id": entity_id,
                        "project_name": project,
                        "category": "decision",
                        "content": f"{query} confirms structured truth isolation",
                        "source": "benchmark:generated-gold",
                        "status": "user_confirmed",
                    }
                ]
                item["expected"]["memory_entry_ids"] = [entity_id]
            elif surface == "observation":
                item["observations"] = [
                    {
                        "id": entity_id,
                        "project_name": project,
                        "session_id": f"session-{entity_id}",
                        "client": "codex",
                        "raw_content": f"{query} confirms evidence isolation",
                        "content_type": "turn",
                        "metadata": {"project_name": project},
                    }
                ]
                item["expected"]["observation_ids"] = [entity_id]
            else:
                item["relation_facts"] = [
                    {
                        "id": entity_id,
                        "project_name": project,
                        "source_entity": f"source-{suffix}",
                        "target_entity": f"target-{suffix}",
                        "relation_type": "supports",
                        "evidence": f"{query} confirms relation isolation",
                        "source": "benchmark:generated-gold",
                        "confidence": 0.9,
                        "status": "user_confirmed",
                    }
                ]
                item["expected"]["relation_fact_ids"] = [entity_id]
            generated.append(item)
    return generated


async def _run_case(case: RetrievalQualityCase, data_dir: Path) -> dict:
    with temporarily_disable_embeddings():
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            for raw in case.memory_entries + case.noise_memory_entries:
                await backend.structured_store.save_memory_entry(MemoryEntry(**raw))
            for raw in case.observations + case.noise_observations:
                await backend.verbatim_store.save(Observation(**raw))
            for raw in case.relation_facts + case.noise_relation_facts:
                await backend.structured_store.save_relation_fact(
                    RelationFact(**raw)
                )

            started_at = time.perf_counter()
            entries, observations = await search_memory(
                backend,
                project_name=case.project_name,
                query=case.query,
                scope=case.search.get("scope", "project"),
                mode=str(case.search.get("mode", "fts")),
                memory_entry_limit=int(case.search.get("memory_entry_limit", 10)),
                observation_limit=int(case.search.get("observation_limit", 10)),
                include_history=bool(case.search.get("include_history", False)),
                deep_recall=bool(case.search.get("deep_recall", False)),
                record_signals=False,
            )
            relation_facts = await search_relation_facts(
                backend,
                project_name=case.project_name,
                query=case.query,
                scope=case.search.get("scope", "project"),
                limit=int(case.search.get("relation_fact_limit", 10)),
                include_history=bool(case.search.get("include_history", False)),
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
            return {
                "case_id": case.id,
                "project_name": case.project_name,
                "query": case.query,
                "elapsed_ms": elapsed_ms,
                "memory_entry_ids": [entry.id for entry in entries],
                "observation_ids": [observation.id for observation in observations],
                "relation_fact_ids": [fact.id for fact in relation_facts],
                "forbidden_memory_entry_ids": _forbidden_hits(
                    [entry.id for entry in entries],
                    case.expected.get("forbidden_memory_entry_ids", []),
                ),
                "forbidden_observation_ids": _forbidden_hits(
                    [observation.id for observation in observations],
                    case.expected.get("forbidden_observation_ids", []),
                ),
                "forbidden_relation_fact_ids": _forbidden_hits(
                    [fact.id for fact in relation_facts],
                    case.expected.get("forbidden_relation_fact_ids", []),
                ),
                "result_project_names": sorted(
                    {
                        project_name
                        for project_name in (
                            _project_name_of(entry) for entry in entries + observations + relation_facts
                        )
                        if project_name
                    }
                ),
                "memory_recall_at_5": _recall_at_k(
                    [entry.id for entry in entries],
                    case.expected.get("memory_entry_ids", []),
                ),
                "observation_recall_at_5": _recall_at_k(
                    [observation.id for observation in observations],
                    case.expected.get("observation_ids", []),
                ),
                "relation_recall_at_5": _recall_at_k(
                    [fact.id for fact in relation_facts],
                    case.expected.get("relation_fact_ids", []),
                ),
                "project_leak_rate": _project_leak_rate(
                    case.project_name,
                    entries + observations + relation_facts,
                ),
                "read_path_only": True,
                "vector_disabled": True,
            }
        finally:
            await backend.close()


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _project_name_of(item: object) -> str | None:
    project_name = getattr(item, "project_name", None)
    if isinstance(project_name, str) and project_name:
        return project_name
    metadata = getattr(item, "metadata", None)
    if isinstance(metadata, dict):
        project_name = metadata.get("project_name")
        if isinstance(project_name, str) and project_name:
            return project_name
    return None


def _recall_at_k(actual_ids: list[str], expected_ids: list[str], k: int = 5) -> float:
    if not expected_ids:
        return 1.0
    actual_top_k = actual_ids[:k]
    return round(len(set(actual_top_k).intersection(expected_ids)) / len(expected_ids), 3)


def _forbidden_hits(actual_ids: list[str], forbidden_ids: list[str]) -> list[str]:
    forbidden = set(forbidden_ids or [])
    return [item for item in actual_ids if item in forbidden]


def _project_leak_rate(target_project: str, results: list[object]) -> float:
    if not results:
        return 0.0
    leaked = sum(1 for item in results if _project_name_of(item) not in {None, target_project})
    return round(leaked / len(results), 3)


def _suite_report(
    results: list[dict[str, Any]],
    cases: list[RetrievalQualityCase] | None = None,
) -> dict[str, Any]:
    latencies = [float(item["elapsed_ms"]) for item in results]
    case_by_id = {case.id: case for case in cases or []}
    if case_by_id:
        expected_total = {
            "memory": sum(
                len(case.expected.get("memory_entry_ids", []))
                for case in case_by_id.values()
            ),
            "observation": sum(
                len(case.expected.get("observation_ids", []))
                for case in case_by_id.values()
            ),
            "relation": sum(
                len(case.expected.get("relation_fact_ids", []))
                for case in case_by_id.values()
            ),
        }
    else:
        expected_total = {
            "memory": sum(1 for item in results for _ in item["memory_entry_ids"]),
            "observation": sum(1 for item in results for _ in item["observation_ids"]),
            "relation": sum(1 for item in results for _ in item["relation_fact_ids"]),
        }
    forbidden_hits = sum(
        len(item.get("forbidden_memory_entry_ids", []))
        + len(item.get("forbidden_observation_ids", []))
        + len(item.get("forbidden_relation_fact_ids", []))
        for item in results
    )
    return {
        "suite": "retrieval_quality_v0_8_24",
        "version": "0.8.24",
        "case_count": len(results),
        "overall_recall_at_5": round(
            sum(
                item["memory_recall_at_5"] * len(item["memory_entry_ids"])
                + item["observation_recall_at_5"] * len(item["observation_ids"])
                + item["relation_recall_at_5"] * len(item["relation_fact_ids"])
                for item in results
            )
            / max(1, sum(expected_total.values())),
            3,
        ),
        "project_leak_rate": round(
            sum(item["project_leak_rate"] for item in results) / max(1, len(results)),
            3,
        ),
        "forbidden_hit_count": forbidden_hits,
        "p95_latency_ms": round(_p95(latencies), 3),
        "vector_disabled": all(item["vector_disabled"] for item in results),
        "llm_free": True,
        "read_path_only": True,
    }


def test_retrieval_quality_benchmark_report_is_stable(tmp_path: Path) -> None:
    fixture = Path(__file__).with_name("retrieval_quality_golden.yaml")
    cases = _load_cases(fixture)
    assert cases

    report = _run(_run_benchmark_suite(cases, tmp_path))
    assert report["suite"] == "retrieval_quality_v0_8_24"
    assert report["version"] == "0.8.24"
    assert report["case_count"] == 60
    assert report["case_count"] == len(cases)
    assert report["overall_recall_at_5"] == 1.0
    assert report["project_leak_rate"] == 0.0
    assert report["forbidden_hit_count"] == 0
    assert report["vector_disabled"] is True
    assert report["llm_free"] is True
    assert report["read_path_only"] is True
    assert report["p95_latency_ms"] > 0


async def _run_benchmark_suite(
    cases: list[RetrievalQualityCase],
    tmp_path: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with temporarily_disable_embeddings():
        for case in cases:
            case_dir = tmp_path / case.id
            case_dir.mkdir()
            backend = LocalMemoryBackend(case_dir)
            await backend.init()
            try:
                for raw in case.memory_entries + case.noise_memory_entries:
                    await backend.structured_store.save_memory_entry(MemoryEntry(**raw))
                for raw in case.observations + case.noise_observations:
                    await backend.verbatim_store.save(Observation(**raw))
                for raw in case.relation_facts + case.noise_relation_facts:
                    await backend.structured_store.save_relation_fact(RelationFact(**raw))
                started_at = time.perf_counter()
                entries, observations = await search_memory(
                    backend,
                    project_name=case.project_name,
                    query=case.query,
                    scope=case.search.get("scope", "project"),
                    mode=str(case.search.get("mode", "fts")),
                    memory_entry_limit=int(case.search.get("memory_entry_limit", 10)),
                    observation_limit=int(case.search.get("observation_limit", 10)),
                    include_history=bool(case.search.get("include_history", False)),
                    deep_recall=bool(case.search.get("deep_recall", False)),
                    record_signals=False,
                )
                relation_facts = await search_relation_facts(
                    backend,
                    project_name=case.project_name,
                    query=case.query,
                    scope=case.search.get("scope", "project"),
                    limit=int(case.search.get("relation_fact_limit", 10)),
                    include_history=bool(case.search.get("include_history", False)),
                )
                elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
                results.append(
                    {
                        "case_id": case.id,
                        "project_name": case.project_name,
                        "query": case.query,
                        "elapsed_ms": elapsed_ms,
                        "memory_entry_ids": [entry.id for entry in entries],
                        "observation_ids": [observation.id for observation in observations],
                        "relation_fact_ids": [fact.id for fact in relation_facts],
                        "forbidden_memory_entry_ids": _forbidden_hits(
                            [entry.id for entry in entries],
                            case.expected.get("forbidden_memory_entry_ids", []),
                        ),
                        "forbidden_observation_ids": _forbidden_hits(
                            [observation.id for observation in observations],
                            case.expected.get("forbidden_observation_ids", []),
                        ),
                        "forbidden_relation_fact_ids": _forbidden_hits(
                            [fact.id for fact in relation_facts],
                            case.expected.get("forbidden_relation_fact_ids", []),
                        ),
                        "result_project_names": sorted(
                            {
                                project_name
                                for project_name in (
                                    _project_name_of(entry)
                                    for entry in entries + observations + relation_facts
                                )
                                if project_name
                            }
                        ),
                        "memory_recall_at_5": _recall_at_k(
                            [entry.id for entry in entries],
                            case.expected.get("memory_entry_ids", []),
                        ),
                        "observation_recall_at_5": _recall_at_k(
                            [observation.id for observation in observations],
                            case.expected.get("observation_ids", []),
                        ),
                        "relation_recall_at_5": _recall_at_k(
                            [fact.id for fact in relation_facts],
                            case.expected.get("relation_fact_ids", []),
                        ),
                        "project_leak_rate": _project_leak_rate(
                            case.project_name,
                            entries + observations + relation_facts,
                        ),
                        "read_path_only": True,
                        "vector_disabled": True,
                    }
                )
            finally:
                await backend.close()
    return _suite_report(results, cases)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round(0.95 * (len(ordered) - 1)))
    return ordered[index]


def test_retrieval_quality_v0_8_24_baseline_fixture_round_trip(tmp_path: Path) -> None:
    fixture = Path(__file__).with_name("retrieval_quality_golden.yaml")
    cases = _load_cases(fixture)
    assert cases

    results = []
    for case in cases:
        case_dir = tmp_path / case.id
        case_dir.mkdir()
        results.append(_run(_run_case(case, case_dir)))

    by_id = {item["case_id"]: item for item in results}
    assert by_id["project_alpha_memory"]["memory_entry_ids"] == ["alpha-memory-1"]
    assert by_id["project_alpha_memory"]["observation_ids"] == []
    assert by_id["project_alpha_memory"]["relation_fact_ids"] == []
    assert by_id["project_beta_mixed_surface"]["memory_entry_ids"] == ["beta-memory-1"]
    assert by_id["project_beta_mixed_surface"]["observation_ids"] == ["beta-observation-1"]
    assert by_id["project_beta_mixed_surface"]["relation_fact_ids"] == ["beta-relation-1"]
    assert by_id["temporal_alpha_history"]["memory_entry_ids"] == [
        "alpha-history-1",
        "alpha-current-1",
    ]
    assert by_id["temporal_alpha_current_default"]["memory_entry_ids"] == [
        "alpha-default-current-1",
    ]
    assert by_id["temporal_alpha_current_default"]["forbidden_memory_entry_ids"] == []
    assert by_id["cross_project_isolation"]["memory_entry_ids"] == ["alpha-isolation-1"]
    assert by_id["cross_project_isolation"]["forbidden_memory_entry_ids"] == []
    assert by_id["cross_project_isolation"]["result_project_names"] == ["retrieval-quality-alpha"]
    assert by_id["cross_project_observation_isolation"]["observation_ids"] == [
        "alpha-observation-isolation-1",
    ]
    assert by_id["cross_project_observation_isolation"]["forbidden_observation_ids"] == []
    assert by_id["cross_project_relation_isolation"]["relation_fact_ids"] == [
        "alpha-relation-isolation-1",
    ]
    assert by_id["cross_project_relation_isolation"]["forbidden_relation_fact_ids"] == []
    assert by_id["abstention_no_false_positive"]["memory_entry_ids"] == []
    assert by_id["abstention_no_false_positive"]["observation_ids"] == []
    assert by_id["abstention_no_false_positive"]["relation_fact_ids"] == []
    assert by_id["vector_off_fallback"]["memory_entry_ids"] == [
        "alpha-vector-fallback-1",
    ]
    assert by_id["vector_off_fallback"]["vector_disabled"] is True

    report = _suite_report(results, cases)
    assert report["suite"] == "retrieval_quality_v0_8_24"
    assert report["version"] == "0.8.24"
    assert report["case_count"] == 60
    assert report["case_count"] == len(cases)
    assert report["llm_free"] is True
    assert report["read_path_only"] is True
    assert report["vector_disabled"] is True
    assert report["overall_recall_at_5"] == 1.0
    assert report["project_leak_rate"] == 0.0
    assert report["forbidden_hit_count"] == 0
    assert report["p95_latency_ms"] > 0


def test_retrieval_quality_fixture_declares_llm_free_local_read_path() -> None:
    fixture = Path(__file__).with_name("retrieval_quality_golden.yaml")
    payload = yaml.safe_load(fixture.read_text(encoding="utf-8"))

    assert payload["suite"] == "retrieval_quality_v0_8_24"
    assert payload["version"] == "0.8.24"
    assert payload["declared_case_count"] == 60
    assert len(_load_cases(fixture)) == 60
    assert payload["backend"] == "LocalMemoryBackend"
    assert payload["llm_free"] is True
    assert payload["mode"] == "read_path_only"


def test_retrieval_quality_golden_ab_gate_allows_only_non_regressing_candidates(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).with_name("retrieval_quality_golden.yaml")
    cases = _load_cases(fixture)
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    baseline = _run(_run_benchmark_suite(cases, baseline_dir))
    candidate = dict(baseline)

    report = build_golden_ab_report(
        baseline=baseline,
        candidate=candidate,
        baseline_name="sqlite_fts_baseline",
        candidate_name="adaptive_rrf_probe",
    ).to_dict()

    assert report["allowed_to_ship"] is True
    assert report["candidate_name"] == "adaptive_rrf_probe"
    assert report["deltas"]["overall_recall_at_5"] == 0.0
    assert report["deltas"]["project_leak_rate"] == 0.0

    regressed = dict(candidate)
    regressed["overall_recall_at_5"] = 0.5
    rejected = build_golden_ab_report(
        baseline=baseline,
        candidate=regressed,
        candidate_name="adaptive_rrf_regression",
    ).to_dict()

    assert rejected["allowed_to_ship"] is False
    assert "candidate reduced overall_recall_at_5" in rejected["reasons"]
