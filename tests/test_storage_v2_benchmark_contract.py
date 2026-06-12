from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_REPORT_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "render_report.py"
RENDER_REPORT_SPEC = importlib.util.spec_from_file_location(
    "benchmark_render_report_storage_v2", RENDER_REPORT_PATH
)
assert RENDER_REPORT_SPEC is not None
assert RENDER_REPORT_SPEC.loader is not None
RENDER_REPORT = importlib.util.module_from_spec(RENDER_REPORT_SPEC)
RENDER_REPORT_SPEC.loader.exec_module(RENDER_REPORT)


def _storage_row(benchmark_id: str) -> dict:
    row = {
        "benchmark_id": benchmark_id,
        "operation": "unit",
        "dataset_id": "storage-v2-synthetic-unit",
        "dataset_hash": "a" * 64,
        "query_pack_id": "unit-pack",
        "command": "python unit",
        "hardware": "unit",
        "commit": "abcdef0",
        "entry_count": 12,
        "json_file_count": 12,
        "p50_ms": 1.0,
        "p95_ms": 2.0,
        "rss_peak_mb": 0.5,
        "disk_bytes": 1234,
        "db_size_bytes": 0,
        "sidecar_size_bytes": 0,
        "fallback_reason": "none",
        "claim_readiness": {"ready": False, "source": "unit", "blocking": ["unit"]},
        "accepted": "yes",
        "acceptance_notes": "unit row",
    }
    if benchmark_id == "migration_roundtrip":
        row.update(
            {
                "dry_run_checksum": "b" * 64,
                "canonical_checksum": "b" * 64,
                "rollback_checksum": "b" * 64,
                "apply_checksum_match": True,
                "rollback_checksum_match": True,
                "claim_readiness": {"ready": True, "source": "unit", "blocking": []},
            }
        )
    if benchmark_id == "local_index_fabric_smoke":
        row.update(
            {
                "manifest_commit": True,
                "interrupted_generation_visible": False,
                "source_fingerprint_drift_detected": True,
                "sidecar_size_bytes": 300,
                "claim_readiness": {"ready": True, "source": "unit", "blocking": []},
            }
        )
    return row


def _write_run(run_dir: Path, benchmark_id: str) -> None:
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "notes").mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "benchmark_id": benchmark_id,
                "run_name": "unit",
                "artifact_state": "diagnostic",
                "release_snapshot": False,
                "result_schema_version": 1,
                "accepted": True,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "dataset.manifest.json").write_text(
        json.dumps({"dataset_id": "storage-v2-synthetic-unit", "dataset_hash": "a" * 64}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# report\n", encoding="utf-8")
    (run_dir / "summary.csv").write_text("benchmark_id\n", encoding="utf-8")
    (run_dir / "notes" / "note.json").write_text("{}", encoding="utf-8")
    (run_dir / "results" / f"{benchmark_id}.json").write_text(
        json.dumps(_storage_row(benchmark_id)),
        encoding="utf-8",
    )


def test_v40_storage_benchmark_collections_are_registered_and_packaged() -> None:
    suite = json.loads((REPO_ROOT / "benchmark-suite" / "suite.json").read_text(encoding="utf-8"))
    packaged = json.loads(
        (REPO_ROOT / "harness_mem" / "resources" / "benchmark_suite" / "suite.json").read_text(
            encoding="utf-8"
        )
    )
    ids = {item["id"] for item in suite["collections"]}
    packaged_ids = {item["id"] for item in packaged["collections"]}

    for benchmark_id in [
        "storage_v2_baseline",
        "migration_roundtrip",
        "local_index_fabric_smoke",
    ]:
        assert benchmark_id in ids
        assert benchmark_id in packaged_ids


def test_storage_v2_report_keeps_public_speedup_claim_locked() -> None:
    report = RENDER_REPORT.build_storage_v2_report(
        [_storage_row("storage_v2_baseline")],
        "storage_v2_baseline",
    )

    assert "## Storage v2 Claim Readiness" in report
    assert "- Storage v2 public performance claim ready: no" in report
    assert "does not switch the default storage backend" in report
    assert "not 10k / 100k / 1M release evidence" in report


def test_migration_roundtrip_report_requires_checksum_matches() -> None:
    report = RENDER_REPORT.build_storage_v2_report(
        [_storage_row("migration_roundtrip")],
        "migration_roundtrip",
    )

    assert "## Roundtrip Checks" in report
    assert "- Contract smoke accepted: yes" in report
    assert "- Blocking rows: none" in report


def test_local_index_fabric_report_records_manifest_last_boundary() -> None:
    report = RENDER_REPORT.build_storage_v2_report(
        [_storage_row("local_index_fabric_smoke")],
        "local_index_fabric_smoke",
    )

    assert "## Manifest-Last Checks" in report
    assert "| storage-v2-synthetic-unit | True | False | True | none |" in report
    assert "runtime index fabric implementation remains a later v4.0.x slice" not in report
    assert "it does not switch the default storage backend" in report


def test_validate_run_accepts_storage_v2_bundles(tmp_path: Path) -> None:
    for benchmark_id in [
        "storage_v2_baseline",
        "migration_roundtrip",
        "local_index_fabric_smoke",
    ]:
        run_dir = tmp_path / benchmark_id
        _write_run(run_dir, benchmark_id)
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
        assert f"OK: validated 1 result files for {benchmark_id}" in result.stdout
