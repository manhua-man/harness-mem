from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_gap_backlog_is_indexed_and_actionable() -> None:
    benchmark_readme = (REPO_ROOT / "benchmark-suite" / "README.md").read_text(
        encoding="utf-8"
    )
    benchmark_catalog = (REPO_ROOT / "benchmark-suite" / "BENCHMARKS.md").read_text(
        encoding="utf-8"
    )
    gaps = (REPO_ROOT / "benchmark-suite" / "GAPS.md").read_text(encoding="utf-8")

    assert "GAPS.md" in benchmark_readme
    assert "GAPS.md" in benchmark_catalog
    assert "Coverage dimensions" in benchmark_catalog

    for gap_id in [
        "GAP-BENCH-001: Client Continuation Value",
        "GAP-BENCH-002: Evidence Safety",
        "GAP-BENCH-003: Temporal Product Query",
        "GAP-BENCH-004: Warm Path Latency Non-Smoke",
        "GAP-BENCH-005: Generated Knowledge Cache and Freshness",
        "GAP-BENCH-006: Auto Maintenance Effectiveness",
        "GAP-BENCH-007: Runtime Health and Observability",
    ]:
        assert gap_id in gaps

    assert "Current status: `ready-to-run`" in gaps
    assert "Current status: `blocked-by-product`" in gaps
    assert "This is the first benchmark to complete" in benchmark_catalog


def test_benchmark_gap_backlog_preserves_no_overclaim_boundaries() -> None:
    gaps = (REPO_ROOT / "benchmark-suite" / "GAPS.md").read_text(encoding="utf-8")

    assert "The smoke bundle contains only `T1 enabled`." in gaps
    assert "No disabled pair exists." in gaps
    assert "No `3-5` paired task set exists." in gaps
    assert "Token values are still `unavailable`" in gaps
    assert "generated material does not contaminate truth" in gaps
    assert "v3.1 Auto Dream Memory Maintenance now exposes `/hm:dream`" in gaps
    assert "No completed artifact bundle measures automatic maintenance effectiveness" in gaps
    assert "v3.1 Auto Dream Memory Maintenance is planning-only" not in gaps
    assert "v3.4.4 ships the local MCP surface cost observer" in gaps
    assert "token budget visibility" in gaps
    assert "Cost discipline is tracked as its own class, not folded into observability." in gaps


def test_benchmark_design_packs_are_registered_and_complete() -> None:
    suite = json.loads(
        (REPO_ROOT / "benchmark-suite" / "suite.json").read_text(encoding="utf-8")
    )
    benchmark_readme = (REPO_ROOT / "benchmark-suite" / "README.md").read_text(
        encoding="utf-8"
    )
    benchmark_runbook = (REPO_ROOT / "benchmark-suite" / "RUNBOOK.md").read_text(
        encoding="utf-8"
    )
    benchmark_catalog = (REPO_ROOT / "benchmark-suite" / "BENCHMARKS.md").read_text(
        encoding="utf-8"
    )

    design_ids = {item["id"] for item in suite["collections"]}

    for benchmark_id in design_ids:
        design_dir = REPO_ROOT / "benchmark-suite" / benchmark_id
        assert (design_dir / "README.md").exists()
        assert (design_dir / "acceptance_checklist.md").exists()
        prompt_path = design_dir / "prompts.json"
        assert prompt_path.exists()

        prompts = json.loads(prompt_path.read_text(encoding="utf-8"))
        assert prompts["benchmark_id"] == benchmark_id
        assert prompts["tasks"]

        assert benchmark_id in benchmark_readme
        assert benchmark_id in benchmark_runbook
        assert f"Benchmark id: `{benchmark_id}`" in benchmark_catalog


def test_blocked_benchmark_design_packs_keep_unlock_conditions() -> None:
    blocked_ids = [
        "generated_knowledge_freshness",
    ]

    for benchmark_id in blocked_ids:
        design_dir = REPO_ROOT / "benchmark-suite" / benchmark_id
        readme = (design_dir / "README.md").read_text(encoding="utf-8")
        prompts = json.loads((design_dir / "prompts.json").read_text(encoding="utf-8"))

        assert "Status: blocked-by-product" in readme
        assert "Unlock Conditions" in readme
        assert prompts["status"] == "blocked-by-product"
        assert prompts["unlock_condition"]

    runtime_readme = (
        REPO_ROOT / "benchmark-suite" / "runtime_health_observability" / "README.md"
    ).read_text(encoding="utf-8")
    runtime_prompts = json.loads(
        (
            REPO_ROOT
            / "benchmark-suite"
            / "runtime_health_observability"
            / "prompts.json"
        ).read_text(encoding="utf-8")
    )
    assert "Status: ready-to-run" in runtime_readme
    assert runtime_prompts["status"] == "ready-to-run"


def test_auto_maintenance_benchmark_is_ready_after_v31_surface_ships() -> None:
    design_dir = REPO_ROOT / "benchmark-suite" / "auto_maintenance_effectiveness"
    readme = (design_dir / "README.md").read_text(encoding="utf-8")
    prompts = json.loads((design_dir / "prompts.json").read_text(encoding="utf-8"))
    catalog = (REPO_ROOT / "benchmark-suite" / "BENCHMARKS.md").read_text(
        encoding="utf-8"
    )

    assert "Status: ready-to-run" in readme
    assert prompts["status"] == "ready-to-run"
    assert "Unlocked by v3.1 Auto Dream Memory Maintenance" in prompts["unlock_condition"]
    assert "v3.1 `/hm:dream` ledger/apply/reject/undo surfaces exist" in catalog
