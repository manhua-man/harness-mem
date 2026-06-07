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
