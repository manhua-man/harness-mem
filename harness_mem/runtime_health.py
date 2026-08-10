"""Runtime health report for v3.4.x."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        report["retrieval_health"] = await _retrieval_health(
            backend,
            data_dir,
            project_name,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"retrieval_health unavailable: {exc}")
        report["retrieval_health"] = {"warnings": [str(exc)]}
    try:
        report["memory_funnel"] = await _memory_funnel(
            backend,
            project_name=project_name,
            window_days=7,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"memory_funnel unavailable: {exc}")
        report["memory_funnel"] = {"warnings": [str(exc)]}
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


async def _retrieval_health(
    backend: LocalMemoryBackend,
    data_dir: Path,
    project_name: str,
) -> dict[str, Any]:
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
        "quality_scorecard": await _retrieval_quality_scorecard(
            backend,
            project_name=project_name,
            window_days=7,
        ),
        "surfaces": rows,
        "recent_high_output_calls": cost.get("recent_high_output_calls", []),
        "top_opportunities": cost.get("top_opportunities", []),
    }


async def _retrieval_quality_scorecard(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    window_days: int,
) -> dict[str, Any]:
    """Summarize project-local retrieval feedback without inferring missing outcomes."""

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    wake_surfaced = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        since=since,
        limit=100000,
    )
    search_hits = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=since,
        limit=100000,
    )
    outcome_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="context_outcome",
        since=since,
        limit=100000,
    )
    abstention_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="retrieval_abstained",
        since=since,
        limit=100000,
    )
    exclusion_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="retrieval_excluded",
        since=since,
        limit=100000,
    )
    surfaced = len(wake_surfaced) + len(search_hits)
    abstained = sum(_signal_count(signal) for signal in abstention_signals)
    stale_excluded = 0
    conflict_excluded = 0
    for signal in exclusion_signals:
        reason = str((signal.context or {}).get("reason") or "").strip().lower()
        if reason in {"stale", "historical", "superseded"}:
            stale_excluded += _signal_count(signal)
        elif reason in {"conflict", "temporal_conflict", "version_conflict"}:
            conflict_excluded += _signal_count(signal)
    excluded_total = stale_excluded + conflict_excluded
    feedback_funnel = _retrieval_feedback_funnel(
        surfaced_signals=[*wake_surfaced, *search_hits],
        outcome_signals=outcome_signals,
    )
    outcome_counts = {
        key: int(feedback_funnel[key])
        for key in ("used", "ignored", "misleading")
    }
    feedback_total = sum(outcome_counts.values())
    insufficient_feedback = feedback_total == 0
    negative = outcome_counts["ignored"] + outcome_counts["misleading"]
    if insufficient_feedback:
        assessment = "insufficient_feedback"
        explanation = (
            "Retrieval activity has no recorded outcome feedback in this window."
            if surfaced
            else "No retrieval activity or outcome feedback was recorded in this window."
        )
    elif outcome_counts["misleading"] > 0 or negative > outcome_counts["used"]:
        assessment = "poor_feedback"
        explanation = "Recorded feedback includes misleading context or more negative than used outcomes."
    else:
        assessment = "feedback_available"
        explanation = "Outcome feedback is available; counts are evidence, not durable truth."

    return {
        "window_days": window_days,
        "project_name": project_name,
        "surfaced": surfaced,
        "abstained": abstained,
        "stale_excluded": stale_excluded,
        "conflict_excluded": conflict_excluded,
        "excluded_total": excluded_total,
        **outcome_counts,
        "feedback_total": feedback_total,
        "missing_feedback": feedback_funnel["missing_feedback"],
        "legacy_uncorrelated": feedback_funnel["legacy_uncorrelated"],
        "orphan_feedback": feedback_funnel["orphan_feedback"],
        "insufficient_feedback": insufficient_feedback,
        "assessment": assessment,
        "explanation": explanation,
    }


async def _memory_funnel(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    window_days: int,
) -> dict[str, Any]:
    """Project a content-free distill-to-use funnel from existing ledgers."""

    jobs = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100000,
    )
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    cohort_jobs = [job for job in jobs if _as_utc(job.created_at) >= since]
    wake_surfaced = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        since=since,
        limit=100000,
    )
    search_hits = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=since,
        limit=100000,
    )
    outcome_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="context_outcome",
        since=since,
        limit=100000,
    )

    memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    confirmed_rules = await backend.structured_store.list_confirmed_rules(project_name)
    relation_facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100000,
    )
    searchable_truth_by_candidate: dict[str, set[str]] = {}
    for record in [*memory_entries, *relation_facts]:
        truth_id = str(getattr(record, "id", "") or "")
        if truth_id:
            searchable_truth_by_candidate.setdefault(truth_id, set()).add(truth_id)
    for rule in confirmed_rules:
        truth_id = str(getattr(rule, "id", "") or "")
        candidate_id = str(getattr(rule, "source_candidate_id", "") or "")
        if truth_id and candidate_id:
            searchable_truth_by_candidate.setdefault(candidate_id, set()).add(
                truth_id
            )
    surfaced_signals = [*wake_surfaced, *search_hits]
    surfaced_source_ids = {
        str(getattr(signal, "target_id", "") or "")
        for signal in surfaced_signals
        if str(getattr(signal, "target_id", "") or "")
    }

    finalized = [job for job in cohort_jobs if job.status == "completed"]
    promoted = [job for job in finalized if job.completion_disposition == "promoted"]
    no_candidate = [
        job for job in finalized if job.completion_disposition == "no_candidate"
    ]
    unsettled = [job for job in finalized if job.completion_disposition is None]
    searchable_jobs = [
        job
        for job in promoted
        if any(
            str(candidate_id) in searchable_truth_by_candidate
            for candidate_id in job.output_candidate_ids
        )
    ]
    surfaced_jobs = [
        job
        for job in searchable_jobs
        if {
            truth_id
            for candidate_id in job.output_candidate_ids
            for truth_id in searchable_truth_by_candidate.get(
                str(candidate_id), set()
            )
        }
        & surfaced_source_ids
    ]
    searchable_job_ids = {job.id for job in searchable_jobs}
    surfaced_job_ids = {job.id for job in surfaced_jobs}
    stages = _distill_stage_counts(
        cohort_jobs,
        searchable_job_ids=searchable_job_ids,
        surfaced_job_ids=surfaced_job_ids,
    )
    by_source_host: list[dict[str, Any]] = []
    for source_host in sorted(
        {_funnel_source_host(job.client) for job in cohort_jobs}
    ):
        host_jobs = [
            job
            for job in cohort_jobs
            if _funnel_source_host(job.client) == source_host
        ]
        host_stages = _distill_stage_counts(
            host_jobs,
            searchable_job_ids=searchable_job_ids,
            surfaced_job_ids=surfaced_job_ids,
        )
        by_source_host.append(
            {
                "source_host": source_host,
                "distinct_jobs": host_stages,
                "conversion": _distill_stage_conversion(host_stages),
            }
        )
    feedback = _retrieval_feedback_funnel(
        surfaced_signals=surfaced_signals,
        outcome_signals=outcome_signals,
    )
    return {
        "schema_version": "harness_mem.memory_funnel.v1",
        "project_name": project_name,
        "distill_scope": "jobs_created_within_window",
        "distill_window_days": window_days,
        "cohort_started_at": since.isoformat(),
        "distill_job_limit": 100000,
        "distill_job_limit_reached": len(jobs) == 100000,
        "retrieval_window_days": window_days,
        "retrieval_signal_limit_per_kind": 100000,
        "retrieval_signal_limit_reached": any(
            len(signals) == 100000
            for signals in (wake_surfaced, search_hits, outcome_signals)
        ),
        "distinct_jobs": stages,
        "conversion": _distill_stage_conversion(stages),
        "by_source_host": by_source_host,
        "finalized": {
            "total": len(finalized),
            "promoted": len(promoted),
            "no_candidate": len(no_candidate),
            "unsettled": len(unsettled),
            "successful_terminal": len(promoted) + len(no_candidate),
        },
        "retrieval_feedback": feedback,
        "interpretation": {
            "no_candidate_is_success": True,
            "missing_feedback_is_not_negative": True,
            "offered_includes_explicit_distill_selection": True,
            "host_dimension": "source_session_host",
            "content_recorded": False,
        },
    }


def _distill_stage_counts(
    jobs: list[Any],
    *,
    searchable_job_ids: set[str],
    surfaced_job_ids: set[str],
) -> dict[str, int]:
    """Count each content-free job once at every stage it reached."""

    return {
        "captured": len(jobs),
        # Explicit /hm:distill selection is an implicit offer even when the
        # automatic wake offer counter was not involved.
        "offered": sum(
            job.last_agent_offered_at is not None or _distill_job_was_claimed(job)
            for job in jobs
        ),
        "claimed": sum(_distill_job_was_claimed(job) for job in jobs),
        "checkpointed": sum(int(job.completed_chunk_count) > 0 for job in jobs),
        "verified": sum(
            str((job.structural_audit or {}).get("coverage") or "") == "complete"
            for job in jobs
        ),
        "finalized": sum(job.status == "completed" for job in jobs),
        "promoted": sum(
            job.status == "completed"
            and job.completion_disposition == "promoted"
            for job in jobs
        ),
        "searchable": sum(job.id in searchable_job_ids for job in jobs),
        "surfaced": sum(job.id in surfaced_job_ids for job in jobs),
    }


def _distill_job_was_claimed(job: Any) -> bool:
    return bool(
        int(job.attempt_count) > 0
        or job.status in {"processing", "reviewing", "completed"}
    )


def _as_utc(value: datetime) -> datetime:
    """Normalize legacy naive timestamps before cohort comparison."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _funnel_source_host(value: Any) -> str:
    """Group stored client aliases under the seven declared product hosts."""

    client = str(value or "unknown").strip().lower()
    aliases = {
        "claude": "claude-code",
        "claude_code": "claude-code",
        "codex-archive": "codex",
        "codex_archive": "codex",
        "open-code": "opencode",
        "open_code": "opencode",
    }
    return aliases.get(client, client)


def _distill_stage_conversion(stages: dict[str, int]) -> dict[str, float | None]:
    """Return adjacent-stage ratios without inventing zero denominators."""

    pairs = (
        ("captured_to_offered", "captured", "offered"),
        ("offered_to_claimed", "offered", "claimed"),
        ("claimed_to_checkpointed", "claimed", "checkpointed"),
        ("checkpointed_to_verified", "checkpointed", "verified"),
        ("verified_to_finalized", "verified", "finalized"),
        ("promoted_to_searchable", "promoted", "searchable"),
        ("searchable_to_surfaced", "searchable", "surfaced"),
    )
    return {
        label: (
            round(stages[numerator] / stages[denominator], 4)
            if stages[denominator] > 0
            else None
        )
        for label, denominator, numerator in pairs
    }


def _retrieval_feedback_funnel(
    *,
    surfaced_signals: list[Any],
    outcome_signals: list[Any],
) -> dict[str, int]:
    """Correlate feedback by opaque retrieval id; never guess legacy outcomes."""

    surfaced_keys = {
        (retrieval_id, str(getattr(signal, "target_id", "") or ""))
        for signal in surfaced_signals
        if (retrieval_id := _signal_retrieval_id(signal)) is not None
        and str(getattr(signal, "target_id", "") or "")
    }
    legacy_surfaced = sum(
        _signal_retrieval_id(signal) is None for signal in surfaced_signals
    )
    outcomes_by_surface: dict[tuple[str, str], set[str]] = {}
    legacy_outcomes = 0
    for signal in outcome_signals:
        retrieval_id = _signal_retrieval_id(signal)
        outcome = str((getattr(signal, "context", None) or {}).get("outcome") or "")
        outcome = outcome.strip().lower()
        if retrieval_id is None:
            legacy_outcomes += 1
            continue
        if outcome in {"used", "ignored", "misleading"}:
            target_id = str(getattr(signal, "target_id", "") or "")
            if target_id:
                outcomes_by_surface.setdefault(
                    (retrieval_id, target_id), set()
                ).add(outcome)

    feedback = {"used": 0, "ignored": 0, "misleading": 0}
    correlated_feedback = 0
    for surface_key in surfaced_keys:
        outcomes = outcomes_by_surface.get(surface_key, set())
        if not outcomes:
            continue
        correlated_feedback += 1
        # A single outcome call normally writes one value for every source. If
        # conflicting calls exist, classify conservatively without inventing use.
        if "misleading" in outcomes:
            feedback["misleading"] += 1
        elif "ignored" in outcomes:
            feedback["ignored"] += 1
        elif "used" in outcomes:
            feedback["used"] += 1

    missing_feedback = len(surfaced_keys) - correlated_feedback + legacy_surfaced
    return {
        "surfaced": len(surfaced_keys) + legacy_surfaced,
        **feedback,
        "missing_feedback": missing_feedback,
        "correlated_retrievals": len({key[0] for key in surfaced_keys}),
        "correlated_surface_occurrences": len(surfaced_keys),
        "correlated_feedback": correlated_feedback,
        "legacy_uncorrelated": legacy_surfaced + legacy_outcomes,
        "legacy_surfaced": legacy_surfaced,
        "legacy_outcomes": legacy_outcomes,
        "orphan_feedback": sum(
            surface_key not in surfaced_keys for surface_key in outcomes_by_surface
        ),
    }


def _signal_retrieval_id(signal: Any) -> str | None:
    value = str(
        (getattr(signal, "context", None) or {}).get("retrieval_id") or ""
    ).strip()
    return value or None


def _signal_count(signal: Any) -> int:
    """Return a non-negative aggregate count for one shadow quality signal."""

    value = getattr(signal, "value", None)
    if value is None:
        return 1
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 1


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
