from __future__ import annotations

import json
from pathlib import Path

from harness_mem.benchmark_matrix import benchmark_matrix_report
from harness_mem.commands.doctor import health_summary
from harness_mem.core.schemas.dream_run import DreamItem, DreamRun
from harness_mem.core.schemas.metabolism_run import MetabolismRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.runtime_cost import (
    analyze_mcp_surface_cost,
    cost_budget_policy,
    observe_mcp_surface_cost,
)
from harness_mem.runtime_health import runtime_health_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.version_drift import version_drift_report
from tests.helpers import run


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cost_budget_policy_marks_budget_exceeded_and_drilldown_metadata():
    result = {
        "success": True,
        "memory_entries": [
            {"id": "entry-1", "source_ids": ["obs-1"]},
            {"id": "entry-2", "source": "manual"},
        ],
    }

    analysis = analyze_mcp_surface_cost(
        "search_memory",
        {"project_name": "demo", "query": "all"},
        result,
        duration_ms=12,
        surface_budgets={"search": 1},
    )

    assert analysis["budget_policy_version"] == "cost-budget-v3.4.4"
    assert analysis["budget_tokens"] == 1
    assert analysis["budget_exceeded"] is True
    assert analysis["truncation"]["truncated_by"] == "budget_policy"
    assert analysis["truncation"]["source_id_count"] >= 2
    assert "source_ids" in analysis["truncation"]["remaining_drilldown"]
    assert cost_budget_policy()["advisory_only"] is True


def test_version_drift_report_detects_stale_plugin_and_slash_assets(tmp_path: Path):
    plugin_root = tmp_path / "plugins" / "harness-mem"
    manifest = plugin_root / ".codex-plugin" / "plugin.json"
    slash = plugin_root / "commands" / "hm" / "status.md"
    skill = plugin_root / "skills" / "harness-mem" / "SKILL.md"
    manifest.parent.mkdir(parents=True)
    slash.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    slash.write_text("old status command", encoding="utf-8")
    skill.write_text("old skill", encoding="utf-8")

    report = version_drift_report(tmp_path)

    assert report["has_drift"] is True
    kinds = {issue["kind"] for issue in report["issues"]}
    assert "version_mismatch" in kinds
    assert "wire_format_mismatch" in kinds
    assert "stale_wire_format" in kinds
    assert report["update_guidance"]


def test_benchmark_matrix_report_tracks_required_surfaces(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = suite / "artifacts" / "accepted-run"
    artifact.mkdir(parents=True)
    (artifact / "run_manifest.json").write_text(
        json.dumps({"run_id": "accepted-run", "accepted": True}),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["gate"]["passed"] is True
    assert report["gate"]["missing_surface_coverage"] == []
    assert report["matrix_version"] == "v3.8.0"
    assert report["taxonomy"]["artifact_states"] == [
        "accepted",
        "partial",
        "failed",
        "quarantined",
    ]
    assert any(
        item["id"] == "client_enabled_vs_disabled"
        for item in report["taxonomy"]["purpose_map"]
    )
    assert {row["surface"] for row in report["surfaces"]} == {
        "wake",
        "search",
        "file_context",
        "wiki_compact",
        "temporal_query",
    }


def test_benchmark_matrix_report_does_not_pass_without_accepted_artifacts(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    artifact = suite / "artifacts" / "unknown-run"
    artifact.mkdir(parents=True)
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (artifact / "run_manifest.json").write_text(
        json.dumps({"run_id": "unknown-run"}),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["gate"]["passed"] is False
    assert report["gate"]["unknown_artifact_runs"] == 1


def test_benchmark_matrix_report_infers_accepted_artifact_from_results(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    artifact = suite / "artifacts" / "result-accepted-run"
    results = artifact / "results"
    results.mkdir(parents=True)
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (artifact / "run_manifest.json").write_text(
        json.dumps(
            {
                "benchmark_id": "client_enabled_vs_disabled",
                "run_name": "result-accepted-run",
            }
        ),
        encoding="utf-8",
    )
    (results / "task-1.json").write_text(
        json.dumps({"task_id": "T1", "accepted": "yes"}),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["release_snapshot"]["accepted_runs"] == 1
    assert report["release_snapshot"]["unknown_runs"] == 0
    assert report["gate"]["passed"] is True
    assert (
        report["release_snapshot"]["latest_run"]["collection_id"]
        == "client_enabled_vs_disabled"
    )


def test_benchmark_matrix_report_exposes_claim_readiness_from_artifacts(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    (suite / "suite.json").parent.mkdir(parents=True, exist_ok=True)
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )

    client_results = suite / "artifacts" / "client-run" / "results"
    client_results.mkdir(parents=True)
    (client_results.parent / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": "client_enabled_vs_disabled"}),
        encoding="utf-8",
    )
    for condition in ("enabled", "disabled"):
        (client_results / f"T1-{condition}.json").write_text(
            json.dumps(
                {
                    "task_id": "T1",
                    "condition": condition,
                    "accepted": "yes",
                    "token_total": "unavailable",
                    "token_usage": {
                        "available": False,
                        "source": "unavailable",
                        "total": None,
                    },
                }
            ),
            encoding="utf-8",
        )

    latency_results = suite / "artifacts" / "latency-run" / "results"
    latency_results.mkdir(parents=True)
    (latency_results.parent / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": "latency_warm_path"}),
        encoding="utf-8",
    )
    (latency_results / "search_hybrid.json").write_text(
        json.dumps(
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "requested_mode": "hybrid",
                "effective_mode": "fts",
                "fallback_reason": "embedding not available",
            }
        ),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["claim_readiness"]["token_cost_saving"]["ready"] is False
    assert "T1/enabled/token_total_unavailable" in report["claim_readiness"][
        "token_cost_saving"
    ]["blocking"]
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["ready"] is False
    assert (
        "search_hybrid/effective_mode=fts/fallback_reason=embedding not available"
        in report["claim_readiness"]["true_vector_hybrid_latency"]["blocking"]
    )
    assert report["claim_readiness"]["retrieval_recall"]["ready"] is False
    assert report["retrieval_shootout"]["ready"] is False


def test_benchmark_matrix_report_marks_claims_ready_when_artifacts_have_required_evidence(
    tmp_path: Path,
):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )

    client_results = suite / "artifacts" / "client-run" / "results"
    client_results.mkdir(parents=True)
    (client_results.parent / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": "client_enabled_vs_disabled"}),
        encoding="utf-8",
    )
    for condition, total in {"enabled": 100, "disabled": 155}.items():
        (client_results / f"T1-{condition}.json").write_text(
            json.dumps(
                {
                    "task_id": "T1",
                    "condition": condition,
                    "accepted": "yes",
                    "token_usage": {
                        "available": True,
                        "source": "codex-session-observer",
                        "total": total,
                    },
                }
            ),
            encoding="utf-8",
        )

    latency_results = suite / "artifacts" / "latency-run" / "results"
    latency_results.mkdir(parents=True)
    (latency_results.parent / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": "latency_warm_path"}),
        encoding="utf-8",
    )
    (latency_results / "search_hybrid.json").write_text(
        json.dumps(
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "fallback_reason": None,
            }
        ),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["claim_readiness"]["token_cost_saving"]["ready"] is True
    assert report["claim_readiness"]["token_cost_saving"]["blocking"] == []
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["ready"] is True
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["blocking"] == []


def test_benchmark_matrix_report_uses_latest_accepted_claim_artifact(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )

    old_latency = suite / "artifacts" / "2026-06-08-latency-old" / "results"
    old_latency.mkdir(parents=True)
    (old_latency.parent / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-08-latency-old",
                "benchmark_id": "latency_warm_path",
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )
    (old_latency / "search_hybrid.json").write_text(
        json.dumps(
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "requested_mode": "hybrid",
                "effective_mode": "fts",
                "fallback_reason": "embedding not available",
            }
        ),
        encoding="utf-8",
    )

    new_latency = suite / "artifacts" / "2026-06-09-latency-new" / "results"
    new_latency.mkdir(parents=True)
    (new_latency.parent / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-09-latency-new",
                "benchmark_id": "latency_warm_path",
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )
    (new_latency / "search_hybrid.json").write_text(
        json.dumps(
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "fallback_reason": None,
            }
        ),
        encoding="utf-8",
    )

    old_client = suite / "artifacts" / "2026-06-08-client-old" / "results"
    old_client.mkdir(parents=True)
    (old_client.parent / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-08-client-old",
                "benchmark_id": "client_enabled_vs_disabled",
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )
    for condition in ("enabled", "disabled"):
        (old_client / f"T1-{condition}.json").write_text(
            json.dumps(
                {
                    "task_id": "T1",
                    "condition": condition,
                    "accepted": "yes",
                    "token_usage": {
                        "available": False,
                        "source": "unavailable",
                        "total": None,
                    },
                }
            ),
            encoding="utf-8",
        )

    new_client = suite / "artifacts" / "2026-06-09-client-new" / "results"
    new_client.mkdir(parents=True)
    (new_client.parent / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-09-client-new",
                "benchmark_id": "client_enabled_vs_disabled",
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )
    for condition, total in {"enabled": 100, "disabled": 155}.items():
        (new_client / f"T1-{condition}.json").write_text(
            json.dumps(
                {
                    "task_id": "T1",
                    "condition": condition,
                    "accepted": "yes",
                    "token_usage": {
                        "available": True,
                        "source": "codex-session-observer",
                        "total": total,
                    },
                }
            ),
            encoding="utf-8",
        )

    report = benchmark_matrix_report(suite)

    assert report["claim_readiness"]["true_vector_hybrid_latency"]["ready"] is True
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["blocking"] == []
    assert report["claim_readiness"]["token_cost_saving"]["ready"] is True
    assert report["claim_readiness"]["token_cost_saving"]["blocking"] == []


def test_benchmark_matrix_report_marks_retrieval_recall_ready_from_true_hybrid_artifacts(
    tmp_path: Path,
):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                    {"id": "true_hybrid_retrieval_shootout"},
                ]
            }
        ),
        encoding="utf-8",
    )

    results = suite / "artifacts" / "retrieval-run" / "results"
    results.mkdir(parents=True)
    (results.parent / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": "true_hybrid_retrieval_shootout"}),
        encoding="utf-8",
    )
    for mode in ("fts", "vector", "hybrid"):
        (results / f"q1-{mode}.json").write_text(
            json.dumps(
                {
                    "query_id": f"q1-{mode}",
                    "query_type": "knowledge-update",
                    "mode": mode,
                    "model_id": "all-MiniLM-L6-v2",
                    "expected_source_ids": ["source-1"],
                    "retrieved_source_ids": ["source-1"],
                    "recall_at_1": 1.0,
                    "recall_at_5": 1.0,
                    "recall_at_10": 1.0,
                    "p50_ms": 10,
                    "p95_ms": 12,
                    "fallback_reason": None,
                    "token_cost_estimate": 0,
                    "accepted": "yes",
                    "acceptance_notes": "fixture row",
                }
            ),
            encoding="utf-8",
        )

    report = benchmark_matrix_report(suite)

    assert report["claim_readiness"]["retrieval_recall"]["ready"] is True
    assert report["claim_readiness"]["retrieval_recall"]["blocking"] == []
    assert report["retrieval_shootout"]["ready"] is True
    assert report["retrieval_shootout"]["modes"] == ["fts", "hybrid", "vector"]
    assert report["retrieval_shootout"]["default_embedding_baseline"] == "all-MiniLM-L6-v2"


def test_benchmark_matrix_report_uses_tracked_release_snapshot_without_raw_artifacts(
    tmp_path: Path,
):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (suite / "release-snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_version": 2,
                "generated_at": "2026-06-08T00:00:00Z",
                "source": "test release snapshot",
                "artifact_run_count": 1,
                "accepted_runs": 1,
                "failed_runs": 0,
                "unknown_runs": 0,
                "gate_passed": True,
                "runs": [
                    {
                        "run_id": "snapshot-run",
                        "collection_id": "client_enabled_vs_disabled",
                        "accepted": True,
                        "claim_boundary": "paired correctness only",
                    }
                ],
                "claim_readiness": {
                    "token_cost_saving": {
                        "ready": False,
                        "dimension": "cost_discipline",
                        "source": "release-snapshot",
                        "blocking": ["client_enabled_vs_disabled/token_total_unavailable"],
                    },
                    "true_vector_hybrid_latency": {
                        "ready": False,
                        "dimension": "performance",
                        "source": "release-snapshot",
                        "blocking": ["search_hybrid/missing"],
                    },
                    "retrieval_recall": {
                        "ready": False,
                        "dimension": "retrieval_recall",
                        "source": "release-snapshot",
                        "blocking": ["true_hybrid_retrieval_shootout/missing"],
                    },
                },
                "retrieval_shootout": {
                    "source": "release-snapshot",
                    "ready": False,
                    "query_count": 0,
                    "modes": [],
                    "fallback_count": 0,
                    "default_embedding_baseline": "all-MiniLM-L6-v2",
                    "embedding_candidates": [
                        "all-MiniLM-L6-v2",
                        "bge-small-en-v1.5",
                        "nomic-embed-text-v1.5",
                    ],
                    "blocking": ["true_hybrid_retrieval_shootout/missing"],
                },
            }
        ),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["release_snapshot"]["accepted_runs"] == 1
    assert report["release_snapshot"]["unknown_runs"] == 0
    assert report["gate"]["passed"] is True
    assert report["release_snapshot"]["latest_run"]["path"].endswith(
        "release-snapshot.json"
    )
    assert report["claim_readiness"]["token_cost_saving"]["source"] == "release-snapshot"
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["ready"] is False
    assert report["claim_readiness"]["retrieval_recall"]["ready"] is False
    assert report["retrieval_shootout"]["source"] == "release-snapshot"


def test_benchmark_matrix_report_rejects_invalid_snapshot_fallback(tmp_path: Path):
    suite = tmp_path / "benchmark-suite"
    suite.mkdir()
    (suite / "suite.json").write_text(
        json.dumps(
            {
                "collections": [
                    {"id": "latency_warm_path"},
                    {"id": "retrieval_diagnostics"},
                    {"id": "generated_knowledge_freshness"},
                    {"id": "temporal_product_query"},
                    {"id": "retrieval_quality_longmemeval"},
                    {"id": "client_enabled_vs_disabled"},
                    {"id": "evidence_safety"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (suite / "release-snapshot.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "run_id": "weak-snapshot-run",
                        "collection_id": "client_enabled_vs_disabled",
                        "accepted": True,
                    }
                ],
                "claim_readiness": {
                    "token_cost_saving": {
                        "ready": False,
                        "dimension": "cost_discipline",
                        "source": "weak-snapshot",
                        "blocking": ["client_enabled_vs_disabled/token_total_unavailable"],
                    },
                    "true_vector_hybrid_latency": {
                        "ready": False,
                        "dimension": "performance",
                        "source": "weak-snapshot",
                        "blocking": ["search_hybrid/missing"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = benchmark_matrix_report(suite)

    assert report["gate"]["passed"] is False
    assert report["gate"]["has_artifacts"] is False
    assert report["release_snapshot"]["artifact_run_count"] == 0
    assert (
        report["claim_readiness"]["token_cost_saving"]["source"]
        == "missing-or-invalid-snapshot"
    )


def test_benchmark_matrix_report_uses_packaged_snapshot_when_repo_suite_missing(
    tmp_path: Path,
):
    missing_suite = tmp_path / "missing-benchmark-suite"

    report = benchmark_matrix_report(missing_suite)

    assert report["release_snapshot"]["accepted_runs"] == 11
    assert report["release_snapshot"]["unknown_runs"] == 0
    assert report["gate"]["passed"] is True
    assert report["claim_readiness"]["token_cost_saving"]["ready"] is False
    assert report["claim_readiness"]["true_vector_hybrid_latency"]["ready"] is True
    assert report["claim_readiness"]["retrieval_recall"]["ready"] is True
    assert report["retrieval_shootout"]["default_embedding_baseline"] == "all-MiniLM-L6-v2"
    assert "client_enabled_vs_disabled" in report["taxonomy"]["use_cases"]


def test_packaged_benchmark_resources_match_repo_sources() -> None:
    package_root = REPO_ROOT / "harness_mem" / "resources" / "benchmark_suite"

    package_suite = json.loads(
        (package_root / "suite.json").read_text(encoding="utf-8")
    )
    repo_suite = json.loads(
        (REPO_ROOT / "benchmark-suite" / "suite.json").read_text(encoding="utf-8")
    )
    package_snapshot = json.loads(
        (package_root / "release-snapshot.json").read_text(encoding="utf-8")
    )
    repo_snapshot = json.loads(
        (REPO_ROOT / "benchmark-suite" / "release-snapshot.json").read_text(
            encoding="utf-8"
        )
    )

    assert package_suite == repo_suite
    assert package_snapshot == repo_snapshot


def test_runtime_health_report_rolls_up_jobs_and_retrieval(
    backend: LocalMemoryBackend,
    tmp_path: Path,
):
    project = "runtime-health-project"
    backend.reflection_job_store.save(
        ReflectionJob(
            id="reflection-failed",
            project_name=project,
            project_root=str(tmp_path),
            kind="reflection",
            status="failed",
            source="agent",
            error="reflection failed",
        )
    )
    backend.reflection_job_store.save(
        ReflectionJob(
            id="dream-retryable",
            project_name=project,
            project_root=str(tmp_path),
            kind="dream",
            status="retryable",
            source="scheduler",
        )
    )
    run(
        backend.structured_store.save_dream_run(
            DreamRun(
                id="dream-run",
                project_name=project,
                status="failed",
                items=[
                    DreamItem(
                        source_kind="memory_entry",
                        source_id="entry-1",
                        proposed_action="mark_stale",
                        final_action="failed",
                        reason="test failure",
                        error="dream item failed",
                    )
                ],
            )
        )
    )
    run(
        backend.structured_store.save_metabolism_run(
            MetabolismRun(
                id="metabolism-run",
                project_name=project,
                status="error",
                notes=["metabolism failed"],
            )
        )
    )

    report = run(
        runtime_health_report(
            backend,
            data_dir=backend.data_dir,
            project_name=project,
            repo_root=tmp_path,
        )
    )

    assert report["job_health"]["reflection"]["failure_count"] == 1
    assert report["job_health"]["dream"]["retryable_count"] == 1
    assert report["job_health"]["dream"]["failure_count"] == 1
    assert report["job_health"]["metabolism"]["failure_count"] == 1
    assert "generated_cache" in report
    assert "retrieval_health" in report
    assert report["graceful_degradation"]["degraded"] is False


def test_health_summary_runtime_slice_uses_backend_data_dir(
    backend: LocalMemoryBackend,
):
    project = "runtime-health-events-project"
    high_output = " ".join(f"token-{idx}" for idx in range(5000))
    observe_mcp_surface_cost(
        data_dir=backend.data_dir,
        tool_name="wake",
        arguments={"project_name": project},
        result={"success": True, "output": high_output},
        duration_ms=25,
    )

    report = run(health_summary(backend, project))

    calls = report["runtime_health"]["retrieval_health"]["recent_high_output_calls"]
    assert calls
    assert calls[0]["project_name"] == project
