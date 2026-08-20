"""Fail-closed reset of generated runtime data while preserving archive sources."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from harness_mem.adapters.codex.archive_adapter import DEFAULT_ARCHIVE_DIR
from harness_mem.maintenance_lock import exclusive_maintenance_run
from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR


def _resolved(path: Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _archive_sources(archive_dir: Path) -> list[Path]:
    if not archive_dir.is_dir():
        raise ValueError(f"archive source directory is unavailable: {archive_dir}")
    sources = sorted(archive_dir.glob("rollout-*.jsonl"))
    if not sources:
        raise ValueError(f"archive source directory has no rollout sessions: {archive_dir}")
    return [source.resolve() for source in sources if source.is_file()]


def _reset_targets(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted(
        (
            child.resolve()
            for child in data_dir.iterdir()
            if child.name != "maintenance"
        ),
        key=lambda child: child.name,
    )


def runtime_reset_plan(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
) -> dict[str, Any]:
    """Describe a source-preserving reset without changing either location."""

    resolved_data = _resolved(data_dir)
    resolved_archive = _resolved(archive_dir)
    if _is_within(resolved_archive, resolved_data) or _is_within(
        resolved_data, resolved_archive
    ):
        raise ValueError("archive source and runtime data paths overlap")
    sources = _archive_sources(resolved_archive)
    targets = _reset_targets(resolved_data)
    return {
        "operation": "runtime_reset",
        "data_dir": str(resolved_data),
        "archive_dir": str(resolved_archive),
        "archive_source_count": len(sources),
        "target_count": len(targets),
        "target_names": [target.name for target in targets],
        "apply": False,
    }


def apply_runtime_reset(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
) -> dict[str, Any]:
    """Delete only generated runtime data under ``data_dir``.

    Archive source files are separately resolved and verified before the lock is
    acquired. The maintenance lock itself is the only temporary item excluded
    from deletion; it is released and removed before returning.
    """

    plan = runtime_reset_plan(data_dir=data_dir, archive_dir=archive_dir)
    resolved_data = Path(plan["data_dir"])
    resolved_data.mkdir(parents=True, exist_ok=True)
    run_id = f"runtime-reset-{uuid4()}"
    with exclusive_maintenance_run(
        resolved_data,
        run_id=run_id,
        operation="runtime-reset",
    ):
        targets = _reset_targets(resolved_data)
        for target in targets:
            if not _is_within(target, resolved_data):
                raise RuntimeError(f"reset target escaped runtime data directory: {target}")
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                raise RuntimeError(f"unsupported reset target: {target}")
        leftovers = _reset_targets(resolved_data)
        if leftovers:
            raise RuntimeError(
                "runtime reset left generated data behind: "
                + ", ".join(target.name for target in leftovers)
            )
    maintenance_dir = resolved_data / "maintenance"
    if maintenance_dir.is_dir() and not any(maintenance_dir.iterdir()):
        maintenance_dir.rmdir()
    return {
        **plan,
        "apply": True,
        "success": True,
        "run_id": run_id,
        "remaining_runtime_items": [
            child.name for child in _reset_targets(resolved_data)
        ],
        "archive_source_count_after": len(_archive_sources(Path(plan["archive_dir"]))),
    }


async def cmd_reset_runtime(
    *,
    archive_dir: str | None,
    apply: bool,
    confirm_runtime_reset: bool,
) -> int:
    """Preview or apply a source-preserving runtime reset from the CLI."""

    selected_archive = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
    if apply and not confirm_runtime_reset:
        print("Refusing reset: --apply requires --confirm-runtime-reset.")
        return 1
    try:
        result = (
            apply_runtime_reset(archive_dir=selected_archive)
            if apply
            else runtime_reset_plan(archive_dir=selected_archive)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Runtime reset failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


__all__ = ["apply_runtime_reset", "cmd_reset_runtime", "runtime_reset_plan"]
