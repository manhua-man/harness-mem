from __future__ import annotations

import importlib.util
import csv
import json
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_REPORT_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "render_report.py"
RENDER_REPORT_SPEC = importlib.util.spec_from_file_location(
    "benchmark_render_report", RENDER_REPORT_PATH
)
assert RENDER_REPORT_SPEC is not None
assert RENDER_REPORT_SPEC.loader is not None
RENDER_REPORT = importlib.util.module_from_spec(RENDER_REPORT_SPEC)
RENDER_REPORT_SPEC.loader.exec_module(RENDER_REPORT)

CLIENT_PAIR_RUNNER_PATH = (
    REPO_ROOT / "benchmark-suite" / "client_enabled_vs_disabled" / "run_codex_pair.py"
)
CLIENT_PAIR_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "benchmark_client_pair_runner", CLIENT_PAIR_RUNNER_PATH
)
assert CLIENT_PAIR_RUNNER_SPEC is not None
assert CLIENT_PAIR_RUNNER_SPEC.loader is not None
CLIENT_PAIR_RUNNER = importlib.util.module_from_spec(CLIENT_PAIR_RUNNER_SPEC)
CLIENT_PAIR_RUNNER_SPEC.loader.exec_module(CLIENT_PAIR_RUNNER)

TOKEN_EXTRACTOR_PATH = (
    REPO_ROOT / "benchmark-suite" / "tools" / "extract_codex_token_usage.py"
)
TOKEN_EXTRACTOR_SPEC = importlib.util.spec_from_file_location(
    "benchmark_token_extractor", TOKEN_EXTRACTOR_PATH
)
assert TOKEN_EXTRACTOR_SPEC is not None
assert TOKEN_EXTRACTOR_SPEC.loader is not None
TOKEN_EXTRACTOR = importlib.util.module_from_spec(TOKEN_EXTRACTOR_SPEC)
TOKEN_EXTRACTOR_SPEC.loader.exec_module(TOKEN_EXTRACTOR)

APPLY_SIDECARS_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "apply_token_usage_sidecars.py"
APPLY_SIDECARS_SPEC = importlib.util.spec_from_file_location(
    "benchmark_apply_token_sidecars", APPLY_SIDECARS_PATH
)
assert APPLY_SIDECARS_SPEC is not None
assert APPLY_SIDECARS_SPEC.loader is not None
APPLY_SIDECARS = importlib.util.module_from_spec(APPLY_SIDECARS_SPEC)
APPLY_SIDECARS_SPEC.loader.exec_module(APPLY_SIDECARS)

BUILD_SNAPSHOT_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "build_release_snapshot.py"
BUILD_SNAPSHOT_SPEC = importlib.util.spec_from_file_location(
    "benchmark_build_release_snapshot", BUILD_SNAPSHOT_PATH
)
assert BUILD_SNAPSHOT_SPEC is not None
assert BUILD_SNAPSHOT_SPEC.loader is not None
BUILD_SNAPSHOT = importlib.util.module_from_spec(BUILD_SNAPSHOT_SPEC)
BUILD_SNAPSHOT_SPEC.loader.exec_module(BUILD_SNAPSHOT)

FILTER_ARCHIVE_PATH = REPO_ROOT / "scripts" / "filter_public_archive.py"
FILTER_ARCHIVE_SPEC = importlib.util.spec_from_file_location(
    "filter_public_archive", FILTER_ARCHIVE_PATH
)
assert FILTER_ARCHIVE_SPEC is not None
assert FILTER_ARCHIVE_SPEC.loader is not None
FILTER_ARCHIVE = importlib.util.module_from_spec(FILTER_ARCHIVE_SPEC)
FILTER_ARCHIVE_SPEC.loader.exec_module(FILTER_ARCHIVE)


def _local_release_artifact_dirs() -> list[Path]:
    artifact_root = REPO_ROOT / "benchmark-suite" / "artifacts"
    if not artifact_root.exists():
        return []
    return sorted(
        path
        for path in artifact_root.iterdir()
        if path.is_dir() and (path / "run_manifest.json").exists()
    )


def _assert_release_snapshot_claims(snapshot: dict[str, object]) -> None:
    claim_readiness = snapshot["claim_readiness"]
    assert isinstance(claim_readiness, dict)
    token_cost_saving = claim_readiness["token_cost_saving"]
    true_vector_hybrid_latency = claim_readiness["true_vector_hybrid_latency"]
    retrieval_recall = claim_readiness["retrieval_recall"]
    assert isinstance(token_cost_saving, dict)
    assert isinstance(true_vector_hybrid_latency, dict)
    assert isinstance(retrieval_recall, dict)
    assert token_cost_saving["ready"] is False
    assert "T1/token_delta_not_saving=-597494" in token_cost_saving["blocking"]
    assert true_vector_hybrid_latency["ready"] is True
    assert retrieval_recall["ready"] is True
    retrieval_shootout = snapshot["retrieval_shootout"]
    assert isinstance(retrieval_shootout, dict)
    assert retrieval_shootout["default_embedding_baseline"] == "all-MiniLM-L6-v2"
    assert retrieval_shootout["ready"] is True



def test_release_snapshot_validates_claim_readiness_contract() -> None:
    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_release_snapshot.py",
            "--path",
            "benchmark-suite/release-snapshot.json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK: validated release snapshot v2 with 13 runs" in result.stdout


def test_build_release_snapshot_matches_tracked_snapshot() -> None:
    snapshot_path = REPO_ROOT / "benchmark-suite" / "release-snapshot.json"
    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not _local_release_artifact_dirs():
        assert current["artifact_run_count"] == 13
        assert current["accepted_runs"] == 13
        assert current["gate_passed"] is True
        _assert_release_snapshot_claims(current)
        return

    rebuilt = BUILD_SNAPSHOT.build_release_snapshot(
        REPO_ROOT / "benchmark-suite",
        generated_at=current["generated_at"],
    )

    assert rebuilt == current
    _assert_release_snapshot_claims(rebuilt)


def test_check_release_artifacts_accepts_current_benchmark_set() -> None:
    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/check_release_artifacts.py",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "release snapshot v2" in result.stdout
    if _local_release_artifact_dirs():
        assert "OK: checked 13 benchmark runs" in result.stdout
        assert "(artifacts, snapshot runs=13)" in result.stdout
    else:
        assert "OK: checked 0 benchmark runs" in result.stdout
        assert "(snapshot-only, snapshot runs=13)" in result.stdout


def test_check_release_artifacts_accepts_snapshot_only_checkout(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    suite_root.mkdir()
    (suite_root / "release-snapshot.json").write_text(
        (REPO_ROOT / "benchmark-suite" / "release-snapshot.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/check_release_artifacts.py",
            "--suite-root",
            str(suite_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK: checked 0 benchmark runs" in result.stdout
    assert "(snapshot-only, snapshot runs=13)" in result.stdout


def test_full_gate_runs_benchmark_release_artifact_check() -> None:
    testing_doc = (REPO_ROOT / "docs" / "testing.md").read_text(encoding="utf-8")
    releasing_doc = (REPO_ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
    ps_full = (REPO_ROOT / "scripts" / "test-full.ps1").read_text(encoding="utf-8")
    sh_full = (REPO_ROOT / "scripts" / "test-full.sh").read_text(encoding="utf-8")
    ci = (REPO_ROOT / ".github" / "workflows" / "test-matrix.yml").read_text(
        encoding="utf-8"
    )
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "python benchmark-suite/tools/check_release_artifacts.py" in testing_doc
    assert "`claim_readiness` gates" in testing_doc
    assert "snapshot-only" in testing_doc
    assert "no:cacheprovider" in testing_doc
    assert ".tmp/pytest-full" in testing_doc
    assert "benchmark release artifacts" in ps_full
    assert "benchmark-suite/tools/check_release_artifacts.py" in ps_full
    assert "no:cacheprovider" in ps_full
    assert ".tmp\\pytest-full" in ps_full
    assert "Running benchmark release artifact check" in sh_full
    assert "benchmark-suite/tools/check_release_artifacts.py" in sh_full
    assert "no:cacheprovider" in sh_full
    assert ".tmp/pytest-full" in sh_full
    assert "Benchmark release artifact check" in ci
    assert "benchmark-suite/tools/check_release_artifacts.py" in ci
    assert "Benchmark release artifact check" in changelog
    assert "Packaged benchmark fallback" in changelog
    assert "snapshot-only" in changelog
    assert "Scripted pytest isolation" in changelog
    assert "## 发版前检查" in releasing_doc
    assert ".\\scripts\\test-full.ps1" in releasing_doc
    assert "bash scripts/test-full.sh" in releasing_doc
    assert "python benchmark-suite/tools/check_release_artifacts.py" in releasing_doc
    assert "`claim_readiness` gates" in releasing_doc
    assert "`snapshot-only`" in releasing_doc


def test_public_source_archive_excludes_benchmark_suite_and_internal_planning() -> None:
    gitattributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    excludes = (REPO_ROOT / "release" / "public-source-excludes.txt").read_text(
        encoding="utf-8"
    )
    ps_archive = (REPO_ROOT / "scripts" / "build-public-source-archive.ps1").read_text(
        encoding="utf-8"
    )
    sh_archive = (REPO_ROOT / "scripts" / "build-public-source-archive.sh").read_text(
        encoding="utf-8"
    )
    releasing_doc = (REPO_ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")

    assert "benchmark-suite/** export-ignore" in gitattributes
    assert "docs/roadmap*.md export-ignore" in gitattributes
    assert "openspec/** export-ignore" in gitattributes
    assert "tests/** export-ignore" in gitattributes
    assert "benchmark-suite/" in excludes
    assert "docs/roadmap*.md" in excludes
    assert "openspec/" in excludes
    assert "tests/" in excludes
    assert "--check-only" in ps_archive
    assert "--check-only" in sh_archive
    assert "`benchmark-suite/**`" in releasing_doc
    assert "公开源码包不携带 benchmark-suite" in releasing_doc


def test_public_archive_filter_drops_benchmark_suite_and_internal_planning(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "harness-mem-3.4.4"
    files = {
        "README.md": "public readme",
        "docs/error-codes.md": "public error docs",
        "benchmark-suite/release-snapshot.json": "{}",
        "benchmark-suite/artifacts/run/results/T1.json": "{}",
        "docs/roadmap-v40.md": "internal roadmap",
        "docs/reference-projects.md": "internal references",
        "openspec/specs/memory.md": "internal spec",
        "tests/test_roadmap.py": "internal test",
        "docs/v2-user-test-packet.md": "maintainer packet",
        "harness_mem/integration/artifacts/transcript.jsonl": "{}",
    }
    for rel, content in files.items():
        path = source_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    archive = tmp_path / "public-source.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source_root, arcname=source_root.name)

    dropped = FILTER_ARCHIVE.filter_archive(
        archive,
        REPO_ROOT / "release" / "public-source-excludes.txt",
    )

    with tarfile.open(archive, "r:gz") as handle:
        names = set(handle.getnames())

    assert dropped >= 8
    assert "harness-mem-3.4.4/README.md" in names
    assert "harness-mem-3.4.4/docs/error-codes.md" in names
    assert not any("benchmark-suite/" in name for name in names)
    assert not any("docs/roadmap" in name for name in names)
    assert not any("reference-projects.md" in name for name in names)
    assert not any("openspec/" in name for name in names)
    assert not any("/tests/" in name for name in names)
    assert not any("docs/v2-user-test-packet.md" in name for name in names)
    assert not any("harness_mem/integration/artifacts/" in name for name in names)


def test_release_snapshot_validator_rejects_missing_claim_readiness(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "release-snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "snapshot_version": 2,
                "generated_at": "2026-06-08T00:00:00Z",
                "source": "test",
                "artifact_run_count": 1,
                "accepted_runs": 1,
                "failed_runs": 0,
                "unknown_runs": 0,
                "gate_passed": True,
                "runs": [
                    {
                        "run_id": "accepted-run",
                        "collection_id": "client_enabled_vs_disabled",
                        "accepted": True,
                        "claim_boundary": "test boundary",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_release_snapshot.py",
            "--path",
            str(snapshot),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "claim_readiness must be an object" in result.stderr


def test_benchmark_gap_backlog_is_indexed_and_actionable() -> None:
    benchmark_readme = (REPO_ROOT / "benchmark-suite" / "README.md").read_text(
        encoding="utf-8"
    )
    benchmark_catalog = (REPO_ROOT / "benchmark-suite" / "BENCHMARKS.md").read_text(
        encoding="utf-8"
    )
    gaps = (REPO_ROOT / "benchmark-suite" / "GAPS.md").read_text(encoding="utf-8")

    assert "GAPS.md" in benchmark_readme
    assert "RESULTS.md" in benchmark_readme
    assert "release-snapshot.json" in benchmark_readme
    assert "check_release_artifacts.py" in benchmark_readme
    assert "build_release_snapshot.py" in benchmark_readme
    assert "validate_release_snapshot.py" in benchmark_readme
    assert "`claim_readiness.token_cost_saving.ready` | `false`" in benchmark_readme
    assert "`claim_readiness.true_vector_hybrid_latency.ready` | `true`" in benchmark_readme
    assert "`claim_readiness.retrieval_recall.ready` | `true`" in benchmark_readme
    assert "codedb-mcp` has a stronger" in benchmark_readme
    assert "GAPS.md" in benchmark_catalog
    assert "Coverage dimensions" in benchmark_catalog
    assert "Retrieval recall" in benchmark_catalog
    assert "true_hybrid_retrieval_shootout" in benchmark_catalog

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

    assert gaps.count("Current status: `closed`") == 7
    assert "Current status: `ready-to-run`" not in gaps
    assert "- `blocked-by-product`:" in gaps
    assert "Completed result summary" in benchmark_catalog
    assert "All executable BENCH gaps are closed as of 2026-06-08" in benchmark_catalog
    assert "BENCH-008 adds a v3.8" in benchmark_catalog
    assert "fixture contract plus a bounded local smoke source-hit recall run" in benchmark_catalog
    assert "does not prove answer correctness or broad" in benchmark_catalog
    assert (
        "No global token-saving claim until a paired run reports a positive "
        "disabled-minus-enabled token/cost delta from a named source."
    ) in benchmark_catalog
    assert "`functional_token_economics` is the separate feature-level fixture benchmark" in benchmark_catalog
    assert "Keep true-hybrid latency claims scoped to the local synthetic fixture" in benchmark_catalog
    assert "blocked until v3.2 generated knowledge surfaces ship" not in benchmark_catalog
    assert "blocked until v3.4 runtime health/cost/regression surfaces ship" not in benchmark_catalog
    assert "no completed paired result" not in benchmark_catalog
    assert "methodology / smoke only until paired runs exist" not in benchmark_catalog
    assert "no completed effectiveness artifact yet" not in benchmark_catalog


def test_benchmark_results_report_artifact_backed_metrics_not_pass_only() -> None:
    results = (REPO_ROOT / "benchmark-suite" / "RESULTS.md").read_text(
        encoding="utf-8"
    )

    assert "2026-06-09 token-visible pair recorded" in results
    assert "disabled - enabled token delta `-597494`" in results
    assert "No token-saving claim" in results
    assert "FTS p95 9.901ms" in results
    assert "`effective_mode=fts`" in results
    assert "Generated claims inspected | 23" in results
    assert "Maintenance actions recorded | 19" in results
    assert "False-success count total | 2" in results
    assert "`budget_tokens=1`, `budget_exceeded=True`" in results
    assert "aggregate delta is `0`" in results
    assert "11` accepted runs, `0` failed runs, `0` unknown runs" in results
    assert "falls back to the tracked" in results
    assert "`benchmark-suite/release-snapshot.json` summary" in results
    assert "| Gate passed | true |" in results
    assert "does not create token-saving" in results
    assert "token_delta_not_saving" not in results
    assert "retrieval recall" in results
    assert "not a real billing benchmark" in results
    assert "Vector Hybrid Claim Readiness" in results
    assert "True vector-hybrid claim ready: yes" in results


def test_benchmark_gap_backlog_preserves_no_overclaim_boundaries() -> None:
    gaps = (REPO_ROOT / "benchmark-suite" / "GAPS.md").read_text(encoding="utf-8")
    bench001_section = gaps.split(
        "### GAP-BENCH-001: Client Continuation Value", 1
    )[1].split("### GAP-BENCH-002: Evidence Safety", 1)[0]
    bench002_section = gaps.split("### GAP-BENCH-002: Evidence Safety", 1)[1].split(
        "### GAP-BENCH-003: Temporal Product Query", 1
    )[0]
    bench003_section = gaps.split(
        "### GAP-BENCH-003: Temporal Product Query", 1
    )[1].split("### GAP-BENCH-004: Warm Path Latency Non-Smoke", 1)[0]
    bench004_section = gaps.split(
        "### GAP-BENCH-004: Warm Path Latency Non-Smoke", 1
    )[1].split("### GAP-BENCH-005: Generated Knowledge Cache and Freshness", 1)[0]

    assert "Current status: `closed`" in bench001_section
    assert "2026-06-08-client_enabled_vs_disabled-codex-paired-t1-t3-01" in gaps
    assert "The completed bundle covers `3` paired tasks" in gaps
    assert "Each completed task has both enabled and disabled results." in gaps
    assert "Disabled results record empty `memory_calls` lists." in gaps
    assert "strong memory-retrieval uplift claim" in gaps
    assert "failed with `429 Too Many Requests`; no paired result is claimed" in gaps
    assert "Token totals remain `unavailable`" in gaps
    assert "Current status: `closed`" in bench002_section
    assert "2026-06-08-evidence_safety-codex-guarded-e1-e5-01" in gaps
    assert "`evidence_found`, `safe_claim`, and" in gaps
    assert "`forbidden_claim_check`" in gaps
    assert "`E5` qualifies a stronger completed/closed benchmark claim" in gaps
    assert "Current status: `closed`" in bench003_section
    assert "2026-06-08-temporal_product_query-codex-temporal-tq1-tq5-01" in gaps
    assert "`current_truth`, `historical_truth`, and" in gaps
    assert "`missing_evidence`" in gaps
    assert "`TQ5` identifies ambiguous temporal scope" in gaps
    assert "v3.3 temporal query and supersede explainability is planning-only" not in gaps
    assert "Current status: `closed`" in bench004_section
    assert "2026-06-08-latency_warm_path-local-nonsmoke-offline-01" in gaps
    assert "effective_mode=fts" in gaps
    assert "fallback_reason=embedding not available" in gaps
    assert "2026-06-08-generated_knowledge_freshness-codex-generated-gk1-gk5-01" in gaps
    assert "`generated_claims`, `source_map_status`, `freshness_status`" in gaps
    assert "`GK1` correctly reports incomplete source-map coverage" in gaps
    assert "`GK5` rejects citation laundering" in gaps
    assert "generated material does not contaminate truth" in gaps
    assert "v3.1 Auto Dream Memory Maintenance now exposes `/hm:dream`" in gaps
    assert "2026-06-08-auto_maintenance_effectiveness-codex-maintenance-am1-am6-01" in gaps
    assert "`maintenance_actions`, `before_state`, `after_state`" in gaps
    assert "`AM4` covers a false-positive rejection path." in gaps
    assert "`AM5` covers undo / rollback evidence and failure handling." in gaps
    assert "guarded repo/test-evidence benchmark, not a live mutation" in gaps
    assert "v3.1 Auto Dream Memory Maintenance is planning-only" not in gaps
    assert "v3.4.4 ships the local MCP surface cost observer" in gaps
    assert "cost budget" in gaps
    assert "2026-06-08-runtime_health_observability-codex-health-rh1-rh6-01" in gaps
    assert "returned `OK: validated 6 result files for runtime_health_observability`" in gaps
    assert "The completed bundle covers `RH1` through `RH6`" in gaps
    assert "`RH6` records `false_success_count=1`" in gaps
    assert "a `429 Too Many Requests` failure is counted as false success" in gaps
    assert "Cost discipline is tracked as its own class, not folded into observability." in gaps
    assert "All benchmark gaps are closed." in gaps


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

    assert "Token-visible rerun flow" in benchmark_runbook
    assert "extract_codex_token_usage.py" in benchmark_runbook
    assert "apply_token_usage_sidecars.py" in benchmark_runbook
    assert "check_release_artifacts.py" in benchmark_runbook
    assert "build_release_snapshot.py" in benchmark_runbook
    assert "--sync-package-resources" in benchmark_runbook
    assert "validate_release_snapshot.py" in benchmark_runbook
    assert "token_usage.available=true" in benchmark_runbook
    assert "Token Claim Readiness" in benchmark_runbook
    assert "Token-saving claim ready: no" in benchmark_runbook
    assert "Vector Hybrid Claim Readiness" in benchmark_runbook
    assert "True vector-hybrid claim ready: yes" in benchmark_runbook
    assert "Retrieval Recall Claim Readiness" in benchmark_runbook


def test_generated_knowledge_benchmark_is_ready_after_v32_surface_ships() -> None:
    design_dir = REPO_ROOT / "benchmark-suite" / "generated_knowledge_freshness"
    readme = (design_dir / "README.md").read_text(encoding="utf-8")
    prompts = json.loads((design_dir / "prompts.json").read_text(encoding="utf-8"))

    assert "Status: ready-to-run" in readme
    assert "Unlock Conditions" in readme
    assert prompts["status"] == "ready-to-run"
    assert "Unlocked by v3.2 generated knowledge compiler" in prompts["unlock_condition"]

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
    assert "v3.1 `/hm:dream` surfaces shipped and AM1-AM6 completed" in catalog


def test_client_pair_report_outcome_uses_fixed_acceptance_enum() -> None:
    assert RENDER_REPORT._pair_outcome("yes", "yes") == "both_passed"
    assert RENDER_REPORT._pair_outcome("yes", "no") == "enabled_only_passed"
    assert RENDER_REPORT._pair_outcome("no", "yes") == "disabled_only_passed"
    assert RENDER_REPORT._pair_outcome("no", "no") == "both_failed"


def test_client_pair_report_uses_token_usage_envelope_for_delta() -> None:
    report = RENDER_REPORT.build_client_report(
        [
            {
                "task_id": "T1",
                "condition": "enabled",
                "accepted": "yes",
                "runtime_seconds": 10,
                "prompt_turns": 1,
                "token_total": 100,
                "token_usage": {
                    "available": True,
                    "source": "sidecar",
                    "total": 100,
                    "input": 80,
                    "output": 20,
                },
                "acceptance_notes": "enabled passed",
            },
            {
                "task_id": "T1",
                "condition": "disabled",
                "accepted": "yes",
                "runtime_seconds": 12,
                "prompt_turns": 1,
                "token_total": 155,
                "token_usage": {
                    "available": True,
                    "source": "sidecar",
                    "total": 155,
                    "input": 130,
                    "output": 25,
                },
                "acceptance_notes": "disabled passed",
            },
        ]
    )

    assert "| T1 | enabled | yes | 10 | 1 | 100 | sidecar | enabled passed |" in report
    assert "| T1 | disabled | yes | 12 | 1 | 155 | sidecar | disabled passed |" in report
    assert "| T1 | 55 | 2.00 | 0 | both_passed |" in report
    assert "- Token-saving claim ready: yes" in report
    assert "- Missing token totals: none" in report


def test_client_pair_report_keeps_unavailable_tokens_distinct_from_zero() -> None:
    report = RENDER_REPORT.build_client_report(
        [
            {
                "task_id": "T1",
                "condition": "enabled",
                "accepted": "yes",
                "runtime_seconds": 10,
                "prompt_turns": 1,
                "token_total": "unavailable",
                "token_usage": {
                    "available": False,
                    "source": "unavailable",
                    "total": None,
                },
                "acceptance_notes": "enabled passed",
            },
            {
                "task_id": "T1",
                "condition": "disabled",
                "accepted": "yes",
                "runtime_seconds": 12,
                "prompt_turns": 1,
                "token_total": "unavailable",
                "token_usage": {
                    "available": False,
                    "source": "unavailable",
                    "total": None,
                },
                "acceptance_notes": "disabled passed",
            },
        ]
    )

    assert "| T1 | enabled | yes | 10 | 1 | unavailable | unavailable | enabled passed |" in report
    assert "| T1 | unavailable | 2.00 | 0 | both_passed |" in report
    assert "- Token-saving claim ready: no" in report
    assert "- Missing token totals: T1/enabled, T1/disabled" in report


def test_client_pair_report_blocks_negative_token_saving_delta() -> None:
    report = RENDER_REPORT.build_client_report(
        [
            {
                "task_id": "T1",
                "condition": "enabled",
                "accepted": "yes",
                "runtime_seconds": 10,
                "prompt_turns": 1,
                "token_usage": {
                    "available": True,
                    "source": "sidecar",
                    "total": 200,
                },
                "acceptance_notes": "enabled used more",
            },
            {
                "task_id": "T1",
                "condition": "disabled",
                "accepted": "yes",
                "runtime_seconds": 12,
                "prompt_turns": 1,
                "token_usage": {
                    "available": True,
                    "source": "sidecar",
                    "total": 120,
                },
                "acceptance_notes": "disabled used less",
            },
        ]
    )

    assert "| T1 | -80 | 2.00 | 0 | both_passed |" in report
    assert "- Token-saving claim ready: no" in report
    assert "- Blocking token-saving rows: T1/token_delta_not_saving=-80" in report


def test_client_pair_summary_csv_normalizes_token_usage(tmp_path: Path) -> None:
    RENDER_REPORT.write_client_summary_csv(
        tmp_path,
        [
            {
                "task_id": "T1",
                "condition": "enabled",
                "client": "codex",
                "model": "gpt-test",
                "workspace_path": str(REPO_ROOT),
                "runtime_seconds": 10,
                "prompt_turns": 1,
                "followup_count": 0,
                "token_total": "unavailable",
                "token_usage": {
                    "available": False,
                    "source": "unavailable",
                    "total": None,
                },
                "accepted": "yes",
                "acceptance_notes": "test",
            }
        ],
    )

    rows = list(csv.DictReader((tmp_path / "summary.csv").open(encoding="utf-8")))

    assert rows[0]["token_total"] == "unavailable"
    assert rows[0]["token_source"] == "unavailable"
    assert rows[0]["token_counter_available"] == "False"


def test_client_pair_runner_reports_unavailable_when_events_have_no_usage(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                '{"type":"thread.started","thread_id":"t"}',
                '{"type":"turn.completed"}',
            ]
        ),
        encoding="utf-8",
    )

    usage = CLIENT_PAIR_RUNNER.token_usage_from_events(events)

    assert usage["available"] is False
    assert usage["source"] == "unavailable"
    assert usage["total"] is None
    assert "did not include usage/token fields" in usage["notes"][0]


def test_client_pair_runner_accepts_token_usage_sidecar(tmp_path: Path) -> None:
    sidecars = tmp_path / "token-sidecars"
    sidecars.mkdir()
    (sidecars / "T1-enabled-token-usage.json").write_text(
        json.dumps(
            {
                "source": "manual",
                "input_tokens": 90,
                "cached_input_tokens": 10,
                "output_tokens": 25,
                "reasoning_tokens": 5,
                "cost_usd": 0.0123,
                "notes": "copied from client usage summary",
            }
        ),
        encoding="utf-8",
    )

    usage = CLIENT_PAIR_RUNNER.token_usage_from_sidecar(sidecars, "T1", "enabled")

    assert usage is not None
    assert usage["available"] is True
    assert usage["source"] == "manual"
    assert usage["total"] == 115
    assert usage["input"] == 90
    assert usage["cached_input"] == 10
    assert usage["output"] == 25
    assert usage["reasoning"] == 5
    assert usage["cost_usd"] == 0.0123


def test_codex_token_extractor_exports_numeric_sidecar_without_text(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    session.write_text(
        "\n".join(
            [
                '{"type":"response_item","payload":{"type":"message","content":[{"text":"secret prompt text"}]}}',
                json.dumps(
                    {
                        "timestamp": "2026-06-08T00:00:00Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 1,
                                    "cached_input_tokens": 2,
                                    "output_tokens": 3,
                                    "reasoning_output_tokens": 4,
                                    "total_tokens": 10,
                                },
                                "last_token_usage": {
                                    "input_tokens": 90,
                                    "cached_input_tokens": 10,
                                    "output_tokens": 25,
                                    "reasoning_output_tokens": 5,
                                    "total_tokens": 130,
                                },
                            },
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    sidecar = TOKEN_EXTRACTOR.build_sidecar(session)

    assert sidecar["available"] is True
    assert sidecar["source"] == "codex-session-observer"
    assert sidecar["total"] == 130
    assert sidecar["input"] == 90
    assert sidecar["cached_input"] == 10
    assert sidecar["output"] == 25
    assert sidecar["reasoning"] == 5
    assert "secret prompt text" not in json.dumps(sidecar)


def _write_minimal_client_run(
    run_dir: Path,
    schema_version: int | None,
    token_usage: dict | None = None,
) -> None:
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "transcripts").mkdir()
    manifest: dict[str, object] = {
        "benchmark_id": "client_enabled_vs_disabled",
        "run_name": "test-run",
        "created_at": "2026-06-08T00:00:00+08:00",
        "client": "codex",
        "model": "gpt-test",
        "workspace_path": str(REPO_ROOT),
        "repo_state": {
            "git_head": "test",
            "git_dirty": True,
        },
        "operator_notes": [],
    }
    if schema_version is not None:
        manifest["result_schema_version"] = schema_version
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# report\n", encoding="utf-8")
    result = {
        "task_id": "T1",
        "condition": "enabled",
        "client": "codex",
        "model": "gpt-test",
        "workspace_path": str(REPO_ROOT),
        "runtime_seconds": 1,
        "prompt_turns": 1,
        "followup_count": 0,
        "token_total": "unavailable",
        "accepted": "yes",
        "acceptance_notes": "test",
    }
    if token_usage is not None:
        result["token_usage"] = token_usage
    (run_dir / "results" / "T1-enabled.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )


def test_validate_run_keeps_legacy_client_token_total_contract(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy-client-run"
    _write_minimal_client_run(run_dir, schema_version=None)

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK: validated 1 result files for client_enabled_vs_disabled" in result.stdout


def test_validate_run_requires_token_usage_for_client_schema_v2(tmp_path: Path) -> None:
    run_dir = tmp_path / "schema-v2-client-run"
    _write_minimal_client_run(run_dir, schema_version=2)

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "missing field 'token_usage'" in result.stderr


def test_validate_run_accepts_client_schema_v2_unavailable_token_usage(tmp_path: Path) -> None:
    run_dir = tmp_path / "schema-v2-unavailable-client-run"
    _write_minimal_client_run(
        run_dir,
        schema_version=2,
        token_usage={
            "available": False,
            "source": "unavailable",
            "total": None,
            "input": None,
            "cached_input": None,
            "output": None,
            "reasoning": None,
            "cost_usd": None,
            "notes": ["client did not expose a stable token counter"],
        },
    )

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK: validated 1 result files for client_enabled_vs_disabled" in result.stdout


def test_validate_run_rejects_available_token_usage_without_numbers(tmp_path: Path) -> None:
    run_dir = tmp_path / "schema-v2-bad-token-client-run"
    _write_minimal_client_run(
        run_dir,
        schema_version=2,
        token_usage={
            "available": True,
            "source": "manual",
            "total": None,
            "input": None,
            "cached_input": None,
            "output": None,
            "reasoning": None,
            "cost_usd": None,
            "notes": ["bad sidecar"],
        },
    )

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "available token_usage requires at least one numeric field" in result.stderr


def test_apply_token_usage_sidecars_upgrades_result_and_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "client-run"
    _write_minimal_client_run(run_dir, schema_version=None)
    notes = run_dir / "notes"
    notes.mkdir()
    (notes / "T1-enabled-token-usage.json").write_text(
        json.dumps(
            {
                "source": "codex-session-observer",
                "total": 130,
                "input": 90,
                "cached_input": 10,
                "output": 25,
                "reasoning": 5,
                "notes": ["numeric sidecar only"],
            }
        ),
        encoding="utf-8",
    )

    summary = APPLY_SIDECARS.apply_sidecars(run_dir, notes)
    result = json.loads((run_dir / "results" / "T1-enabled.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert summary["missing"] == []
    assert summary["manifest_schema_updated"] is True
    assert manifest["result_schema_version"] == 2
    assert result["token_total"] == 130
    assert result["token_source"] == "codex-session-observer"
    assert result["token_counter_available"] is True
    assert result["token_usage"]["output"] == 25

    validation = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert validation.returncode == 0
    assert "OK: validated 1 result files for client_enabled_vs_disabled" in validation.stdout


def test_apply_sidecars_then_render_report_computes_token_delta(tmp_path: Path) -> None:
    run_dir = tmp_path / "paired-client-run"
    _write_minimal_client_run(run_dir, schema_version=None)
    disabled = json.loads((run_dir / "results" / "T1-enabled.json").read_text(encoding="utf-8"))
    disabled["condition"] = "disabled"
    disabled["runtime_seconds"] = 12
    (run_dir / "results" / "T1-disabled.json").write_text(
        json.dumps(disabled),
        encoding="utf-8",
    )

    notes = run_dir / "notes"
    notes.mkdir()
    (notes / "T1-enabled-token-usage.json").write_text(
        json.dumps(
            {
                "source": "codex-session-observer",
                "total": 100,
                "input": 80,
                "output": 20,
                "notes": ["enabled numeric sidecar"],
            }
        ),
        encoding="utf-8",
    )
    (notes / "T1-disabled-token-usage.json").write_text(
        json.dumps(
            {
                "source": "codex-session-observer",
                "total": 155,
                "input": 130,
                "output": 25,
                "notes": ["disabled numeric sidecar"],
            }
        ),
        encoding="utf-8",
    )

    APPLY_SIDECARS.apply_sidecars(run_dir, notes)
    rows = RENDER_REPORT.load_results(run_dir / "results")
    report = RENDER_REPORT.build_report(rows, "client_enabled_vs_disabled")

    assert "| T1 | enabled | yes | 1 | 1 | 100 | codex-session-observer | test |" in report
    assert "| T1 | disabled | yes | 12 | 1 | 155 | codex-session-observer | test |" in report
    assert "| T1 | 55 | 11.00 | 0 | both_passed |" in report
    assert "- Token-saving claim ready: yes" in report


def test_single_condition_report_does_not_render_pair_table() -> None:
    report = RENDER_REPORT.build_client_report(
        [
            {
                "task_id": "E1",
                "condition": "guarded",
                "accepted": "yes",
                "runtime_seconds": 1.23,
                "prompt_turns": 1,
                "token_total": "unavailable",
                "acceptance_notes": "safe claim boundary preserved",
            }
        ]
    )

    assert "## Paired Delta Table" not in report
    assert "missing_pair" not in report


def test_retrieval_shootout_report_blocks_fixture_only_recall_claims() -> None:
    rows = [
        {
            "query_id": f"Q1-{mode}",
            "query_type": "knowledge-update",
            "mode": mode,
            "model_id": "all-MiniLM-L6-v2",
            "expected_source_ids": ["source-a"],
            "retrieved_source_ids": ["source-a"],
            "recall_at_1": 1.0,
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "fallback_reason": None,
            "token_cost_estimate": 0,
            "fixture_only": True,
            "accepted": "yes",
        }
        for mode in ["fts", "vector", "hybrid"]
    ]

    report = RENDER_REPORT.build_retrieval_shootout_report(rows)

    assert "## Retrieval Recall Claim Readiness" in report
    assert "- Retrieval recall claim ready: no" in report
    assert "fixture_only=false" in report
    assert "Q1-fts/fixture_only" in report
    assert "Q1-vector/fixture_only" in report
    assert "Q1-hybrid/fixture_only" in report


def test_latency_report_marks_fts_fallback_as_not_true_hybrid_ready() -> None:
    report = RENDER_REPORT.build_latency_report(
        [
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "sample_count": 40,
                "p50_ms": 11.017,
                "p95_ms": 13.171,
                "p99_ms": 13.970,
                "max_ms": 14.384,
                "requested_mode": "hybrid",
                "effective_mode": "fts",
                "fallback_reason": "embedding not available",
            }
        ]
    )

    assert "## Vector Hybrid Claim Readiness" in report
    assert "- True vector-hybrid claim ready: no" in report
    assert (
        "- Blocking rows: search_hybrid/effective_mode=fts/fallback_reason=embedding not available"
    ) in report


def test_latency_report_marks_real_hybrid_as_claim_ready() -> None:
    report = RENDER_REPORT.build_latency_report(
        [
            {
                "task_id": "search_hybrid",
                "accepted": "yes",
                "sample_count": 40,
                "p50_ms": 9.1,
                "p95_ms": 12.2,
                "p99_ms": 13.3,
                "max_ms": 14.4,
                "requested_mode": "hybrid",
                "effective_mode": "hybrid",
                "fallback_reason": None,
            }
        ]
    )

    assert "- True vector-hybrid claim ready: yes" in report
    assert "- Blocking rows: none" in report


def test_latency_report_requires_a_hybrid_row_for_claim_readiness() -> None:
    report = RENDER_REPORT.build_latency_report(
        [
            {
                "task_id": "search_fts",
                "accepted": "yes",
                "sample_count": 40,
                "p50_ms": 4.9,
                "p95_ms": 9.9,
                "p99_ms": 12.3,
                "max_ms": 12.8,
                "requested_mode": "fts",
                "effective_mode": "fts",
                "fallback_reason": None,
            }
        ]
    )

    assert "- True vector-hybrid claim ready: no" in report
    assert "- Blocking rows: search_hybrid/missing" in report


def _memory_shortcut_row(
    task_id: str,
    task_type: str,
    condition: str,
    *,
    tokens: int,
    source_reads: int,
    repo_calls: int,
    input_tokens: int | None = None,
    cached_input: int | None = None,
    output_tokens: int | None = None,
    reasoning_tokens: int | None = None,
) -> dict:
    token_usage = {
        "available": True,
        "source": "unit-test",
        "total": tokens,
    }
    if input_tokens is not None:
        token_usage["input"] = input_tokens
    if cached_input is not None:
        token_usage["cached_input"] = cached_input
    if output_tokens is not None:
        token_usage["output"] = output_tokens
    if reasoning_tokens is not None:
        token_usage["reasoning"] = reasoning_tokens

    return {
        "task_id": task_id,
        "task_type": task_type,
        "condition": condition,
        "accepted": "yes",
        "runtime_seconds": 1.0,
        "token_usage": token_usage,
        "source_read_count": source_reads,
        "repo_calls": [f"call-{index}" for index in range(repo_calls)],
        "memory_calls": ["provided_memory_packet:test"] if condition == "enabled" else [],
        "acceptance_notes": "unit test row",
    }


def test_memory_shortcut_report_blocks_source_budget_violations() -> None:
    rows = []
    for index in range(1, 9):
        enabled_reads = 3 if index == 8 else 1
        rows.extend(
            [
                _memory_shortcut_row(
                    f"MS{index}",
                    "long_source_recovery",
                    "enabled",
                    tokens=50,
                    source_reads=enabled_reads,
                    repo_calls=1,
                ),
                _memory_shortcut_row(
                    f"MS{index}",
                    "long_source_recovery",
                    "disabled",
                    tokens=100,
                    source_reads=4,
                    repo_calls=4,
                ),
            ]
        )
    for index in range(1, 3):
        rows.extend(
            [
                _memory_shortcut_row(
                    f"NC{index}",
                    "negative_control",
                    "enabled",
                    tokens=50,
                    source_reads=1,
                    repo_calls=1,
                ),
                _memory_shortcut_row(
                    f"NC{index}",
                    "negative_control",
                    "disabled",
                    tokens=50,
                    source_reads=1,
                    repo_calls=1,
                ),
            ]
        )

    report = RENDER_REPORT.build_memory_shortcut_report(rows)

    assert "MS8/budget=enabled_source_reads>2" in report
    assert "- Memory-shortcut saving claim ready: no" in report


def test_memory_shortcut_report_blocks_negative_control_budget_violations() -> None:
    rows = []
    for index in range(1, 9):
        rows.extend(
            [
                _memory_shortcut_row(
                    f"MS{index}",
                    "long_source_recovery",
                    "enabled",
                    tokens=50,
                    source_reads=1,
                    repo_calls=1,
                ),
                _memory_shortcut_row(
                    f"MS{index}",
                    "long_source_recovery",
                    "disabled",
                    tokens=100,
                    source_reads=4,
                    repo_calls=4,
                ),
            ]
        )
    rows.extend(
        [
            _memory_shortcut_row(
                "NC1",
                "negative_control",
                "enabled",
                tokens=50,
                source_reads=1,
                repo_calls=4,
            ),
            _memory_shortcut_row(
                "NC1",
                "negative_control",
                "disabled",
                tokens=50,
                source_reads=1,
                repo_calls=1,
            ),
            _memory_shortcut_row(
                "NC2",
                "negative_control",
                "enabled",
                tokens=50,
                source_reads=1,
                repo_calls=1,
            ),
            _memory_shortcut_row(
                "NC2",
                "negative_control",
                "disabled",
                tokens=50,
                source_reads=1,
                repo_calls=1,
            ),
        ]
    )

    report = RENDER_REPORT.build_memory_shortcut_report(rows)

    assert "NC1/budget=enabled:negative_control_repo_calls>3" in report
    assert "negative_control_budget_ok_pairs=1/2" in report
    assert "- Memory-shortcut saving claim ready: no" in report


def test_memory_shortcut_report_keeps_cache_adjusted_proxy_diagnostic_only() -> None:
    rows = [
        _memory_shortcut_row(
            "MS1",
            "long_source_recovery",
            "enabled",
            tokens=300,
            source_reads=1,
            repo_calls=1,
            input_tokens=280,
            cached_input=240,
            output_tokens=20,
            reasoning_tokens=0,
        ),
        _memory_shortcut_row(
            "MS1",
            "long_source_recovery",
            "disabled",
            tokens=200,
            source_reads=4,
            repo_calls=4,
            input_tokens=170,
            cached_input=0,
            output_tokens=30,
            reasoning_tokens=0,
        ),
    ]

    report = RENDER_REPORT.build_memory_shortcut_report(rows)

    assert "| MS1 | long_source_recovery | -100 | -0.500 | 140 | 0.700 |" in report
    assert "- Median cache-adjusted saving ratio: 0.700" in report
    assert "- Memory-shortcut saving claim ready: no" in report
    assert "MS1/token_delta_not_saving=-100" in report
    assert "This proxy is diagnostic only" in report


def _functional_token_economics_row(
    scenario_id: str = "FTE1",
    *,
    baseline_tokens: int = 1000,
    optimized_tokens: int = 250,
    accepted: str = "yes",
    fixture_only: bool = True,
) -> dict:
    token_delta = baseline_tokens - optimized_tokens
    saving_ratio = token_delta / baseline_tokens if baseline_tokens > 0 else 0.0
    return {
        "scenario_id": scenario_id,
        "workflow": "progressive_recall",
        "title": "Progressive recall vs broad source recovery",
        "baseline_label": "read broad source docs before answering",
        "optimized_label": "search index -> timeline -> selected details",
        "baseline_tokens": baseline_tokens,
        "optimized_tokens": optimized_tokens,
        "token_delta": token_delta,
        "saving_ratio": round(saving_ratio, 4),
        "minimum_saving_ratio": 0.5,
        "baseline_source_count": 1,
        "optimized_source_count": 1,
        "baseline_sources": [
            {
                "kind": "file",
                "path": "docs/reference-projects.md",
                "chars": 10000,
            }
        ],
        "optimized_sources": [
            {
                "kind": "text",
                "label": "compact progressive recall packet",
                "chars": 1000,
            }
        ],
        "tokenizer": "tiktoken",
        "token_source": "harness_mem.commands.token_estimator",
        "fixture_only": fixture_only,
        "claim_scope": "fixture progressive recall payload",
        "accepted": accepted,
        "acceptance_notes": "unit test row",
    }


def _write_functional_token_economics_run(
    run_dir: Path,
    row: dict | None = None,
) -> None:
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "notes").mkdir()
    payload = row or _functional_token_economics_row()
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "benchmark_id": "functional_token_economics",
                "run_name": "unit",
                "artifact_state": "diagnostic",
                "release_snapshot": False,
                "result_schema_version": 1,
                "created_at": "2026-06-10T00:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# report\n", encoding="utf-8")
    (run_dir / "summary.csv").write_text("scenario_id\nFTE1\n", encoding="utf-8")
    (run_dir / "notes" / "scenarios.json").write_text(
        json.dumps({"benchmark_id": "functional_token_economics", "scenarios": []}),
        encoding="utf-8",
    )
    (run_dir / "results" / f"{payload['scenario_id']}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_functional_token_economics_report_keeps_global_claim_locked() -> None:
    report = RENDER_REPORT.build_functional_token_economics_report(
        [
            _functional_token_economics_row("FTE1", baseline_tokens=1000, optimized_tokens=250),
            _functional_token_economics_row("FTE2", baseline_tokens=900, optimized_tokens=300),
        ]
    )

    assert "## Feature-Level Claim Readiness" in report
    assert "- Functional fixture token-economics ready: yes" in report
    assert "- Median saving ratio: 0.708" in report
    assert "## Global Claim Boundary" in report
    assert "- Global token/cost saving ready: no" in report
    assert "does not prove real billing" in report


def test_functional_token_economics_summary_csv(tmp_path: Path) -> None:
    rows = [_functional_token_economics_row("FTE1")]

    RENDER_REPORT.write_functional_token_economics_summary_csv(tmp_path, rows)

    csv_rows = list(csv.DictReader((tmp_path / "summary.csv").open(encoding="utf-8")))
    assert csv_rows[0]["scenario_id"] == "FTE1"
    assert csv_rows[0]["baseline_tokens"] == "1000"
    assert csv_rows[0]["optimized_tokens"] == "250"
    assert csv_rows[0]["saving_ratio"] == "0.75"
    assert csv_rows[0]["fixture_only"] == "True"


def test_validate_run_accepts_functional_token_economics_bundle(tmp_path: Path) -> None:
    run_dir = tmp_path / "functional-token-economics"
    _write_functional_token_economics_run(run_dir)

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "OK: validated 1 result files for functional_token_economics" in result.stdout


def test_validate_run_rejects_functional_token_economics_negative_delta(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "functional-token-economics-negative"
    row = _functional_token_economics_row(
        baseline_tokens=100,
        optimized_tokens=150,
        accepted="no",
    )
    _write_functional_token_economics_run(run_dir, row)

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "token_delta must be a non-negative number" in result.stderr


def test_validate_run_rejects_functional_token_economics_non_fixture(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "functional-token-economics-non-fixture"
    _write_functional_token_economics_run(
        run_dir,
        _functional_token_economics_row(fixture_only=False),
    )

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_run.py",
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "fixture_only must be true for this fixture collection" in result.stderr
