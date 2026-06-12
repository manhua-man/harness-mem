from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from harness_mem.benchmark_matrix import benchmark_matrix_report


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_REPORT_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "render_report.py"
RENDER_REPORT_SPEC = importlib.util.spec_from_file_location(
    "benchmark_render_report_v45",
    RENDER_REPORT_PATH,
)
assert RENDER_REPORT_SPEC is not None
assert RENDER_REPORT_SPEC.loader is not None
RENDER_REPORT = importlib.util.module_from_spec(RENDER_REPORT_SPEC)
RENDER_REPORT_SPEC.loader.exec_module(RENDER_REPORT)


def test_v44_claim_promotion_gate_keeps_public_claims_blocked() -> None:
    report = benchmark_matrix_report(REPO_ROOT / "benchmark-suite")

    gate = report["claim_promotion_gate"]
    assert report["matrix_version"] == "v4.5.0"
    assert gate["passed"] is True
    assert gate["policy_enforced"] is True
    assert set(gate["blocked_claims"]) == {
        "token_cost_saving",
        "storage_v2_speedup",
        "default_reranker_hyde",
        "code_memory_token_runtime",
    }
    assert set(gate["bounded_claims"]) == {
        "true_vector_hybrid_latency",
        "retrieval_recall",
    }
    assert gate["unsafe_promotions"] == []


def test_v45_release_evidence_pack_checks_clean_checkout_resources() -> None:
    report = benchmark_matrix_report(REPO_ROOT / "benchmark-suite")

    release_pack = report["release_evidence_pack"]
    assert release_pack["passed"] is True
    assert release_pack["collection_present"] is True
    assert release_pack["accepted_runs"] == 18
    assert release_pack["failed_runs"] == 0
    assert release_pack["unknown_runs"] == 0
    assert release_pack["packaged_resource_match"]["matches"] is True
    assert release_pack["claim_promotion_policy_enforced"] is True


def test_v44_v45_artifacts_validate_with_release_tools() -> None:
    for run_dir, expected in [
        (
            "benchmark-suite/artifacts/2026-06-13-claim_promotion_pack-v440-contract",
            "OK: validated 6 result files for claim_promotion_pack",
        ),
        (
            "benchmark-suite/artifacts/2026-06-13-release_evidence_pack-v450-contract",
            "OK: validated 1 result files for release_evidence_pack",
        ),
    ]:
        result = subprocess.run(
            [
                "python",
                "benchmark-suite/tools/validate_run.py",
                "--run-dir",
                run_dir,
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0
        assert expected in result.stdout


def test_v44_v45_report_renderers_show_claim_boundaries() -> None:
    claim_rows = RENDER_REPORT.load_results(
        REPO_ROOT
        / "benchmark-suite"
        / "artifacts"
        / "2026-06-13-claim_promotion_pack-v440-contract"
        / "results"
    )
    claim_report = RENDER_REPORT.build_report(claim_rows, "claim_promotion_pack")
    assert "## Claim Promotion Gate" in claim_report
    assert "Blocked claims: code_memory_token_runtime" in claim_report
    assert "Bounded local claims: retrieval_recall, true_vector_hybrid_latency" in claim_report

    release_rows = RENDER_REPORT.load_results(
        REPO_ROOT
        / "benchmark-suite"
        / "artifacts"
        / "2026-06-13-release_evidence_pack-v450-contract"
        / "results"
    )
    release_report = RENDER_REPORT.build_report(release_rows, "release_evidence_pack")
    assert "## Evidence Packs" in release_report
    assert "| release-evidence-v450 | 18 | 18 | 0 | 0 | 4 | 2 | True | True |" in release_report
    assert "does not turn blocked claims into public performance" in release_report
