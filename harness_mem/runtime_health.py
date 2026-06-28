"""Runtime health report for v3.4.x."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_mem.runtime_cost import surface_cost_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.version_drift import version_drift_report


async def runtime_health_report(
    backend: LocalMemoryBackend,
    *,
    data_dir: Path,
    project_name: str,
    profile: Any = None,
    project_root: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Compose v3.4 runtime health slices without mutating runtime state."""
    warnings: list[str] = []
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
    }
    try:
        report["job_health"] = await _job_health(backend, project_name)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"job_health unavailable: {exc}")
        report["job_health"] = {"warnings": [str(exc)]}
    try:
        report["retrieval_health"] = _retrieval_health(data_dir, project_name)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"retrieval_health unavailable: {exc}")
        report["retrieval_health"] = {"warnings": [str(exc)]}
    try:
        report["version_drift"] = version_drift_report(repo_root)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"version_drift unavailable: {exc}")
        report["version_drift"] = {"warnings": [str(exc)]}
    report["graceful_degradation"] = {
        "degraded": bool(warnings),
        "warnings": warnings,
        "fallbacks": [
            "wake/search continue even when health slices are unavailable",
            "cost observer failures are advisory and never block MCP tool results",
        ],
    }
    return report


async def _job_health(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    dream_jobs = backend.reflection_job_store.list(
        project_name=project_name,
        kind="dream",
        limit=100,
    )
    dream_runs = await backend.structured_store.list_dream_runs(project_name, limit=20)
    return {
        "dream": _run_summary(dream_runs, job_rows=dream_jobs),
    }


def _run_summary(runs: list[Any], *, job_rows: list[Any] | None = None) -> dict[str, Any]:
    latest = runs[0] if runs else None
    failed_runs = [
        run
        for run in runs
        if str(getattr(run, "status", "")).lower() in {"failed", "error"}
        or _run_failed_count(run) > 0
    ]
    retryable_jobs = [
        job for job in (job_rows or []) if getattr(job, "status", None) == "retryable"
    ]
    return {
        "last_run_id": getattr(latest, "id", None) if latest else None,
        "last_run_at": _iso(getattr(latest, "started_at", None)) if latest else None,
        "last_status": getattr(latest, "status", None) if latest else None,
        "failure_count": len(failed_runs),
        "retryable_count": len(retryable_jobs),
        "latest_error": _latest_run_error(failed_runs[0]) if failed_runs else None,
    }


def _retrieval_health(data_dir: Path, project_name: str) -> dict[str, Any]:
    cost = surface_cost_report(data_dir, project_name=project_name, days=7, limit=500)
    surfaces = {
        row["surface"]: row
        for row in cost.get("surfaces", [])
        if row.get("surface") in {"wake", "search", "file_context", "timeline", "temporal_query"}
    }
    rows = []
    for surface, stats in sorted(surfaces.items()):
        calls = max(1, int(stats.get("call_count") or 0))
        rows.append(
            {
                "surface": surface,
                "call_count": stats.get("call_count", 0),
                "avg_latency_ms": stats.get("avg_duration_ms", 0),
                "avg_result_count": _avg_result_count(stats),
                "truncation_frequency": round(
                    int(stats.get("high_output_calls") or 0) / calls,
                    3,
                ),
                "high_output_calls": stats.get("high_output_calls", 0),
            }
        )
    return {
        "window_days": cost.get("window_days", 7),
        "surfaces": rows,
        "recent_high_output_calls": cost.get("recent_high_output_calls", []),
        "top_opportunities": cost.get("top_opportunities", []),
    }


def _avg_result_count(stats: dict[str, Any]) -> float:
    total = 0
    count = 0
    for shape in stats.get("result_shapes", []) or []:
        for key in (
            "memory_entry_count",
            "observation_count",
            "count",
            "total_count",
            "item_count",
            "record_count",
            "timeline_count",
        ):
            if key not in shape:
                continue
            try:
                total += int(shape[key])
                count += 1
            except (TypeError, ValueError):
                pass
    return round(total / count, 1) if count else 0.0


def _run_failed_count(run: Any) -> int:
    summary = getattr(run, "handling_summary", None) or getattr(run, "output_counts", None) or {}
    try:
        return int(summary.get("failed") or summary.get("errors") or 0)
    except (TypeError, ValueError):
        return 0


def _latest_run_error(run: Any) -> str | None:
    for item in getattr(run, "items", []) or []:
        error = getattr(item, "error", None)
        if error:
            return str(error)
    notes = getattr(run, "notes", None)
    if notes:
        return "; ".join(str(note) for note in notes[:3])
    return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


__all__ = ["runtime_health_report"]
