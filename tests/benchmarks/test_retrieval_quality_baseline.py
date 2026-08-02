from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.read_api import search_memory, search_relation_facts
from harness_mem.search.retrieval_quality import build_golden_ab_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate fixture keys instead of accepting silent overrides."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class RetrievalQualityCase:
    id: str
    task_type: str
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
    payload = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_UniqueKeyLoader,
    )
    raw_cases = [*payload["queries"], *_expand_generated_matrix(payload)]
    cases = [
        RetrievalQualityCase(
            id=item["id"],
            task_type=str(item.get("task_type") or "surface_isolation"),
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
    """Run one case and retain an explicit error artifact on runner failure."""

    try:
        return await _run_case_impl(case, data_dir)
    except Exception as exc:  # benchmark failures are data, not silent passes
        return _unscored_artifact(
            case,
            status="error",
            reason=type(exc).__name__,
        )


async def _run_case_impl(case: RetrievalQualityCase, data_dir: Path) -> dict:
    requested_status = str(case.expected.get("evaluation_status") or "scored")
    if requested_status in {"skipped", "error"}:
        return _unscored_artifact(
            case,
            status=requested_status,
            reason=str(
                case.expected.get("evaluation_reason")
                or ("missing_gold" if requested_status == "skipped" else "fixture_error")
            ),
        )
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
            memory_ids = [entry.id for entry in entries]
            observation_ids = [observation.id for observation in observations]
            relation_ids = [fact.id for fact in relation_facts]
            artifact = {
                "case_id": case.id,
                "task_type": case.task_type,
                "project_name": case.project_name,
                "query": case.query,
                "evaluation_status": "scored",
                "evaluation_reason": None,
                "elapsed_ms": elapsed_ms,
                "memory_entry_ids": memory_ids,
                "observation_ids": observation_ids,
                "relation_fact_ids": relation_ids,
                "gold_ids": {
                    "memory_entry_ids": list(case.expected.get("memory_entry_ids", [])),
                    "observation_ids": list(case.expected.get("observation_ids", [])),
                    "relation_fact_ids": list(case.expected.get("relation_fact_ids", [])),
                },
                "retrieved_ids": {
                    "memory_entry_ids": memory_ids,
                    "observation_ids": observation_ids,
                    "relation_fact_ids": relation_ids,
                },
                "retrieval_trace": {
                    "scope": case.search.get("scope", "project"),
                    "mode": case.search.get("mode", "fts"),
                    "include_history": bool(case.search.get("include_history", False)),
                    "project_name": case.project_name,
                    "source_kinds": [
                        kind
                        for kind, ids in (
                            ("memory_entry", memory_ids),
                            ("observation", observation_ids),
                            ("relation_fact", relation_ids),
                        )
                        if ids
                    ],
                },
                "forbidden_memory_entry_ids": _forbidden_hits(
                    memory_ids,
                    case.expected.get("forbidden_memory_entry_ids", []),
                ),
                "forbidden_observation_ids": _forbidden_hits(
                    observation_ids,
                    case.expected.get("forbidden_observation_ids", []),
                ),
                "forbidden_relation_fact_ids": _forbidden_hits(
                    relation_ids,
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
                    memory_ids,
                    case.expected.get("memory_entry_ids", []),
                ),
                "observation_recall_at_5": _recall_at_k(
                    observation_ids,
                    case.expected.get("observation_ids", []),
                ),
                "relation_recall_at_5": _recall_at_k(
                    relation_ids,
                    case.expected.get("relation_fact_ids", []),
                ),
                "project_leak_rate": _project_leak_rate(
                    case.project_name,
                    entries + observations + relation_facts,
                ),
                "read_path_only": True,
                "vector_disabled": True,
            }
            _attach_task_metrics(artifact, case)
            return artifact
        finally:
            await backend.close()


def _unscored_artifact(
    case: RetrievalQualityCase,
    *,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "task_type": case.task_type,
        "project_name": case.project_name,
        "query": case.query,
        "evaluation_status": status,
        "evaluation_reason": reason,
        "elapsed_ms": 0.0,
        "memory_entry_ids": [],
        "observation_ids": [],
        "relation_fact_ids": [],
        "gold_ids": {
            "memory_entry_ids": list(case.expected.get("memory_entry_ids", [])),
            "observation_ids": list(case.expected.get("observation_ids", [])),
            "relation_fact_ids": list(case.expected.get("relation_fact_ids", [])),
        },
        "retrieved_ids": {
            "memory_entry_ids": [],
            "observation_ids": [],
            "relation_fact_ids": [],
        },
        "retrieval_trace": {},
        "forbidden_memory_entry_ids": [],
        "forbidden_observation_ids": [],
        "forbidden_relation_fact_ids": [],
        "result_project_names": [],
        "memory_recall_at_5": 0.0,
        "observation_recall_at_5": 0.0,
        "relation_recall_at_5": 0.0,
        "project_leak_rate": 0.0,
        "read_path_only": True,
        "vector_disabled": True,
        "task_outcome": status,
        "recall_any_at_5": None,
        "recall_all_at_5": None,
        "recall_any_at_10": None,
        "recall_all_at_10": None,
        "ndcg_at_5": None,
        "ndcg_at_10": None,
        "should_abstain": False,
        "predicted_abstain": False,
    }


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


def _attach_task_metrics(
    artifact: dict[str, Any],
    case: RetrievalQualityCase,
) -> None:
    actual_ids = [
        *artifact["memory_entry_ids"],
        *artifact["observation_ids"],
        *artifact["relation_fact_ids"],
    ]
    expected_ids = [
        *case.expected.get("memory_entry_ids", []),
        *case.expected.get("observation_ids", []),
        *case.expected.get("relation_fact_ids", []),
    ]
    should_abstain = not expected_ids
    predicted_abstain = not actual_ids
    all_retrieved = bool(expected_ids) and set(expected_ids).issubset(actual_ids)
    artifact.update(
        {
            "task_outcome": (
                "abstained"
                if should_abstain and predicted_abstain
                else "answered"
                if all_retrieved
                else "misleading"
                if should_abstain
                else "partial"
            ),
            "recall_any_at_5": _recall_any_at_k(actual_ids, expected_ids, 5),
            "recall_all_at_5": _recall_all_at_k(actual_ids, expected_ids, 5),
            "recall_any_at_10": _recall_any_at_k(actual_ids, expected_ids, 10),
            "recall_all_at_10": _recall_all_at_k(actual_ids, expected_ids, 10),
            "ndcg_at_5": _ndcg_at_k(actual_ids, expected_ids, 5),
            "ndcg_at_10": _ndcg_at_k(actual_ids, expected_ids, 10),
            "should_abstain": should_abstain,
            "predicted_abstain": predicted_abstain,
        }
    )


def _recall_any_at_k(
    actual_ids: list[str], expected_ids: list[str], k: int
) -> float | None:
    if not expected_ids:
        return None
    return float(bool(set(actual_ids[:k]).intersection(expected_ids)))


def _recall_all_at_k(
    actual_ids: list[str], expected_ids: list[str], k: int
) -> float | None:
    if not expected_ids:
        return None
    return float(set(expected_ids).issubset(actual_ids[:k]))


def _ndcg_at_k(actual_ids: list[str], expected_ids: list[str], k: int) -> float | None:
    if not expected_ids:
        return None
    from math import log2

    expected = set(expected_ids)
    dcg = sum(
        1.0 / log2(index + 2)
        for index, item in enumerate(actual_ids[:k])
        if item in expected
    )
    ideal = sum(1.0 / log2(index + 2) for index in range(min(k, len(expected))))
    return round(dcg / ideal, 3) if ideal else 0.0


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
    scored = [item for item in results if item.get("evaluation_status") == "scored"]
    latencies = [float(item["elapsed_ms"]) for item in scored]
    forbidden_hits = sum(
        len(item.get("forbidden_memory_entry_ids", []))
        + len(item.get("forbidden_observation_ids", []))
        + len(item.get("forbidden_relation_fact_ids", []))
        for item in results
    )
    status_counts: dict[str, int] = {}
    task_counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("evaluation_status") or "error")
        status_counts[status] = status_counts.get(status, 0) + 1
        task_type = str(item.get("task_type") or "unknown")
        task_counts[task_type] = task_counts.get(task_type, 0) + 1
    should_abstain = sum(bool(item.get("should_abstain")) for item in scored)
    predicted_abstain = sum(bool(item.get("predicted_abstain")) for item in scored)
    abstain_true_positive = sum(
        bool(item.get("should_abstain")) and bool(item.get("predicted_abstain"))
        for item in scored
    )
    abstention_precision = (
        round(abstain_true_positive / predicted_abstain, 3)
        if predicted_abstain
        else 1.0
    )
    abstention_recall = (
        round(abstain_true_positive / should_abstain, 3)
        if should_abstain
        else 1.0
    )

    def mean_metric(name: str) -> float:
        values = [float(item[name]) for item in scored if item.get(name) is not None]
        return round(sum(values) / len(values), 3) if values else 0.0

    overall_hits = 0
    overall_expected = 0
    for item in scored:
        expected_ids = {
            *item.get("gold_ids", {}).get("memory_entry_ids", []),
            *item.get("gold_ids", {}).get("observation_ids", []),
            *item.get("gold_ids", {}).get("relation_fact_ids", []),
        }
        retrieved_ids = {
            *item.get("memory_entry_ids", []),
            *item.get("observation_ids", []),
            *item.get("relation_fact_ids", []),
        }
        overall_hits += len(expected_ids.intersection(retrieved_ids))
        overall_expected += len(expected_ids)

    return {
        "suite": "retrieval_quality_v0_9_7",
        "version": "0.9.7",
        "case_count": len(results),
        "scored_case_count": len(scored),
        "evaluation_status_counts": status_counts,
        "task_type_counts": task_counts,
        "query_artifacts": [
            {
                "case_id": item["case_id"],
                "task_type": item.get("task_type"),
                "evaluation_status": item.get("evaluation_status"),
                "evaluation_reason": item.get("evaluation_reason"),
                "gold_ids": item.get("gold_ids", {}),
                "retrieved_ids": item.get("retrieved_ids", {}),
                "task_outcome": item.get("task_outcome"),
                "retrieval_trace": item.get("retrieval_trace", {}),
            }
            for item in results
        ],
        "recall_any_at_5": mean_metric("recall_any_at_5"),
        "recall_all_at_5": mean_metric("recall_all_at_5"),
        "recall_any_at_10": mean_metric("recall_any_at_10"),
        "recall_all_at_10": mean_metric("recall_all_at_10"),
        "ndcg_at_5": mean_metric("ndcg_at_5"),
        "ndcg_at_10": mean_metric("ndcg_at_10"),
        "task_answer_rate": round(
            sum(item.get("task_outcome") == "answered" for item in scored)
            / max(1, len(scored)),
            3,
        ),
        "abstention_precision": abstention_precision,
        "abstention_recall": abstention_recall,
        "overall_recall_at_5": round(
            overall_hits / max(1, overall_expected),
            3,
        ),
        "project_leak_rate": round(
            sum(item["project_leak_rate"] for item in scored) / max(1, len(scored)),
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
    assert report["suite"] == "retrieval_quality_v0_9_7"
    assert report["version"] == "0.9.7"
    assert report["case_count"] == 60
    assert report["case_count"] == len(cases)
    assert report["overall_recall_at_5"] == 1.0
    assert report["project_leak_rate"] == 0.0
    assert report["forbidden_hit_count"] == 0
    assert report["vector_disabled"] is True
    assert report["llm_free"] is True
    assert report["read_path_only"] is True
    assert report["p95_latency_ms"] > 0
    assert report["scored_case_count"] == 58
    assert report["evaluation_status_counts"] == {
        "scored": 58,
        "skipped": 1,
        "error": 1,
    }
    for task_type in {
        "single_hop",
        "cross_session_synthesis",
        "temporal_reasoning",
        "knowledge_update",
        "preference",
        "no_evidence",
        "conflict",
    }:
        assert report["task_type_counts"][task_type] >= 1
    assert report["recall_any_at_5"] == 1.0
    assert report["recall_all_at_5"] == 1.0
    assert report["ndcg_at_5"] == 1.0
    assert report["abstention_precision"] == 1.0
    assert report["abstention_recall"] == 1.0
    assert len(report["query_artifacts"]) == 60


def test_retrieval_quality_repeated_runs_keep_ids_and_outcomes_stable(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).with_name("retrieval_quality_golden.yaml")
    cases = _load_cases(fixture)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _run(_run_benchmark_suite(cases, first_dir))
    second = _run(_run_benchmark_suite(cases, second_dir))
    assert first["query_artifacts"] == second["query_artifacts"]
    assert first["evaluation_status_counts"] == second["evaluation_status_counts"]
    assert first["abstention_precision"] == second["abstention_precision"]
    assert first["abstention_recall"] == second["abstention_recall"]


async def _run_benchmark_suite(
    cases: list[RetrievalQualityCase],
    tmp_path: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        case_dir = tmp_path / case.id
        case_dir.mkdir()
        results.append(await _run_case(case, case_dir))
    return _suite_report(results, cases)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round(0.95 * (len(ordered) - 1)))
    return ordered[index]


def test_retrieval_quality_v0_9_7_fixture_round_trip(tmp_path: Path) -> None:
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
    assert report["suite"] == "retrieval_quality_v0_9_7"
    assert report["version"] == "0.9.7"
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

    assert payload["suite"] == "retrieval_quality_v0_9_7"
    assert payload["version"] == "0.9.7"
    assert payload["declared_case_count"] == 60
    assert len(_load_cases(fixture)) == 60
    assert payload["backend"] == "LocalMemoryBackend"
    assert payload["llm_free"] is True
    assert payload["mode"] == "read_path_only"


def test_retrieval_quality_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    fixture = tmp_path / "duplicate.yaml"
    fixture.write_text(
        "suite: first\nsuite: second\nqueries: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ConstructorError, match="duplicate key 'suite'"):
        _load_cases(fixture)


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
