"""v4.0.5 distribution and release-gate reporting."""

from __future__ import annotations

from pathlib import Path
import platform
import sys
from typing import Any

from harness_mem.index_fabric import load_current_manifest
from harness_mem.rust_core import rust_core_status


WHEEL_TARGETS: tuple[str, ...] = (
    "windows-x86_64",
    "windows-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "linux-x86_64",
    "linux-aarch64",
)

RELEASE_GATE_COMMANDS: tuple[str, ...] = (
    "python -m pytest -q",
    "python -m ruff check .",
    "python -m mypy harness_mem",
    "cargo test --workspace",
    "python benchmark-suite/tools/validate_run.py <v4 smoke artifact>",
)


def distribution_report(
    *,
    repo_root: Path,
    data_dir: Path,
    index_dir: Path | None = None,
) -> dict[str, Any]:
    """Return doctor-friendly v4.0.5 distribution and fallback state."""

    repo_root = Path(repo_root)
    data_dir = Path(data_dir)
    index_dir = index_dir or data_dir / "store_v2" / "index"
    rust = rust_core_status()
    manifest = load_current_manifest(index_dir)
    cargo_workspace = repo_root / "Cargo.toml"
    crate_manifest = repo_root / "crates" / "harness_mem_core_rs" / "Cargo.toml"
    return {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
        },
        "wheel_matrix": {
            "targets": list(WHEEL_TARGETS),
            "current_target": _current_target(),
            "native_available": rust.available,
        },
        "rust_core": rust.to_dict(),
        "fallback": {
            "mode": "native" if rust.available else "pure_python",
            "read_path_hard_fail": False,
            "reason": rust.fallback_reason,
        },
        "local_build": {
            "cargo_workspace": str(cargo_workspace),
            "cargo_workspace_present": cargo_workspace.exists(),
            "crate_manifest": str(crate_manifest),
            "crate_manifest_present": crate_manifest.exists(),
            "command": "cargo test --workspace",
        },
        "index_fabric": {
            "index_dir": str(index_dir),
            "manifest_present": manifest is not None,
            "generation_id": manifest.generation_id if manifest else None,
            "sidecar_count": len(manifest.sidecars) if manifest else 0,
            "freshness": "current-manifest-present" if manifest else "not-built",
        },
        "release_gate": {
            "commands": list(RELEASE_GATE_COMMANDS),
            "requires_benchmark_smoke": True,
            "requires_public_claim_gate": True,
        },
        "public_claim_gate": {
            "readme_performance_claims": "artifact-bounded-only",
            "fallback_must_be_reported": True,
        },
        "binary_size_budget": {
            "wheel_size_mb_max": 25,
            "cold_import_ms_max": 250,
            "doctor_startup_ms_max": 1000,
        },
    }


def _current_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("windows"):
        prefix = "windows"
    elif system.startswith("darwin"):
        prefix = "macos"
    elif system.startswith("linux"):
        prefix = "linux"
    else:
        prefix = system or "unknown"
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    return f"{prefix}-{arch}"


__all__ = ["RELEASE_GATE_COMMANDS", "WHEEL_TARGETS", "distribution_report"]
