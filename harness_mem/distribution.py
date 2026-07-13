"""Distribution and local build reporting."""

from __future__ import annotations

from pathlib import Path
import platform
import sys
from typing import Any

from harness_mem.index_fabric import load_current_manifest
from harness_mem.rust_core import rust_core_status, rust_policy


WHEEL_TARGETS: tuple[str, ...] = (
    "windows-x86_64",
    "windows-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "linux-x86_64",
    "linux-aarch64",
)

RELEASE_GATE_COMMANDS: tuple[str, ...] = (
    "python -m compileall harness_mem",
    "python -m ruff check harness_mem plugins tools",
    "python -m harness_mem.cli --help",
    "cargo test --workspace",
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
    policy = rust_policy()
    warnings = _rust_distribution_warnings(rust, policy)
    manifest = load_current_manifest(index_dir)
    cargo_workspace = repo_root / "Cargo.toml"
    crate_manifest = repo_root / "crates" / "harness_mem_core_rs" / "Cargo.toml"
    payload: dict[str, Any] = {
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
        "rust_policy": policy,
        "fallback": {
            "mode": "native" if rust.available else "pure_python",
            "read_path_hard_fail": policy == "required",
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
            "requires_extra_smoke": False,
        },
        "binary_size_budget": {
            "wheel_size_mb_max": 25,
            "cold_import_ms_max": 250,
            "doctor_startup_ms_max": 1000,
        },
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


def _rust_distribution_warnings(rust: Any, policy: str) -> list[str]:
    warnings: list[str] = []
    if policy == "force_python":
        warnings.append(
            "HARNESS_MEM_RUST=force_python: hot path is intentionally using python_fallback"
        )
        return warnings
    if not rust.available and policy == "required":
        warnings.append(
            "HARNESS_MEM_RUST=required but harness_mem_core_rs is not installed; "
            "read-path calls will fail with HM-203"
        )
        return warnings
    if not rust.available and policy == "prefer":
        warnings.append(
            "rust core running in python_fallback; reinstall harness-mem from a native "
            "GitHub Release wheel or run "
            "'maturin develop --features python-extension' locally"
        )
    return warnings


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
