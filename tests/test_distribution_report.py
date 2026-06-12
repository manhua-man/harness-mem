from __future__ import annotations

import json
from pathlib import Path

from harness_mem.distribution import WHEEL_TARGETS, distribution_report
from harness_mem.index_fabric import build_index_generation


def test_distribution_report_exposes_rust_fallback_and_release_gate(data_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    report = distribution_report(repo_root=repo_root, data_dir=data_dir)

    assert report["wheel_matrix"]["targets"] == list(WHEEL_TARGETS)
    assert report["fallback"]["read_path_hard_fail"] is False
    assert report["local_build"]["cargo_workspace_present"] is True
    assert report["local_build"]["crate_manifest_present"] is True
    assert "python -m pytest -q" in report["release_gate"]["commands"]
    assert "cargo test --workspace" in report["release_gate"]["commands"]
    assert report["public_claim_gate"]["readme_performance_claims"] == (
        "artifact-bounded-only"
    )


def test_distribution_report_reads_index_manifest_freshness(
    data_dir: Path,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    (source / "mem.json").write_text(
        json.dumps({"id": "mem", "content": "distribution manifest"}),
        encoding="utf-8",
    )
    index_dir = data_dir / "store_v2" / "index"
    build_index_generation(source, index_dir, generation_id="gen-distribution")

    report = distribution_report(
        repo_root=repo_root,
        data_dir=data_dir,
        index_dir=index_dir,
    )

    assert report["index_fabric"]["manifest_present"] is True
    assert report["index_fabric"]["generation_id"] == "gen-distribution"
    assert report["index_fabric"]["sidecar_count"] == 4
