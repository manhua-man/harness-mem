from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_driver(
    relative_driver: str,
    *,
    run_name: str,
    artifact_root: Path,
    extra_args: list[str] | None = None,
) -> Path:
    args = [
        "python",
        relative_driver,
        "--run-name",
        run_name,
        "--artifacts-root",
        str(artifact_root),
    ]
    if extra_args:
        args.extend(extra_args)
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return artifact_root / run_name


def _validate_run(run_dir: Path) -> None:
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
    assert result.returncode == 0, result.stderr


def test_canonical_store_runtime_driver_writes_valid_bundle(tmp_path: Path) -> None:
    run_dir = _run_driver(
        "benchmark-suite/canonical_store_runtime_baseline/driver.py",
        run_name="unit-canonical-runtime",
        artifact_root=tmp_path / "artifacts",
        extra_args=["--entry-count", "24", "--samples", "2"],
    )

    _validate_run(run_dir)
    result = json.loads(
        (run_dir / "results" / "canonical_store_runtime_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert result["canonical_row_count"] > 0
    assert isinstance(result["checksum_match"], bool)
    assert "## Canonical Store Checks" in report


def test_storage_v2_baseline_driver_can_mark_release_snapshot(tmp_path: Path) -> None:
    run_dir = _run_driver(
        "benchmark-suite/storage_v2_baseline/driver.py",
        run_name="unit-storage-v2-10k",
        artifact_root=tmp_path / "artifacts",
        extra_args=[
            "--profile",
            "10k",
            "--samples",
            "1",
            "--payload-size-bytes",
            "64",
            "--release-snapshot",
        ],
    )

    _validate_run(run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_state"] == "accepted"
    assert manifest["release_snapshot"] is True


def test_migration_roundtrip_driver_can_mark_release_snapshot(tmp_path: Path) -> None:
    run_dir = _run_driver(
        "benchmark-suite/migration_roundtrip/driver.py",
        run_name="unit-migration-10k",
        artifact_root=tmp_path / "artifacts",
        extra_args=[
            "--profile",
            "10k",
            "--payload-size-bytes",
            "64",
            "--release-snapshot",
        ],
    )

    _validate_run(run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_state"] == "accepted"
    assert manifest["release_snapshot"] is True


def test_index_fabric_runtime_driver_writes_valid_bundle(tmp_path: Path) -> None:
    run_dir = _run_driver(
        "benchmark-suite/index_fabric_runtime_conformance/driver.py",
        run_name="unit-index-runtime",
        artifact_root=tmp_path / "artifacts",
        extra_args=["--entry-count", "24", "--release-snapshot"],
    )

    _validate_run(run_dir)
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    result_files = sorted((run_dir / "results").glob("*.json"))
    assert len(result_files) == 4
    assert manifest["artifact_state"] == "accepted"
    assert manifest["release_snapshot"] is True
    assert "## Runtime Conformance Checks" in report


def test_rust_core_hot_path_driver_writes_valid_bundle(tmp_path: Path) -> None:
    run_dir = _run_driver(
        "benchmark-suite/rust_core_hot_path/driver.py",
        run_name="unit-rust-hot-path",
        artifact_root=tmp_path / "artifacts",
    )

    _validate_run(run_dir)
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    result_files = sorted((run_dir / "results").glob("*.json"))
    assert len(result_files) == 5
    assert "## Rust Mode Checks" in report


def test_rust_core_hot_path_release_snapshot_requires_native_module(
    tmp_path: Path,
) -> None:
    args = [
        "python",
        "benchmark-suite/rust_core_hot_path/driver.py",
        "--run-name",
        "unit-rust-release",
        "--artifacts-root",
        str(tmp_path / "artifacts"),
        "--release-snapshot",
    ]
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode == 0:
        manifest = json.loads(
            (tmp_path / "artifacts" / "unit-rust-release" / "run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["artifact_state"] == "accepted"
        assert manifest["release_snapshot"] is True
    else:
        assert "native harness_mem_core_rs module" in result.stderr
