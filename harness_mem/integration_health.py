"""Compact, factual project integration diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any

from harness_mem.adapters import AdapterRegistry
from harness_mem.autonomous.authorization import (
    background_reason_message,
    background_status,
)
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.hook_receipts import (
    HOOK_RECEIPT_FRESHNESS_SECONDS,
    inspect_hook_execution_receipt,
    read_hook_execution_receipt,
)
from harness_mem.hook_runtime import collect_hook_file_statuses
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_AUTONOMOUS_TOKEN_WARNING = 15_000
_AUTONOMOUS_SECONDS_WARNING = 60.0
_DISTILL_STALLED_HOURS_WARNING = 2.0
_SEMANTIC_SUCCESS_STALE_HOURS = 24.0


async def build_integration_health(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path | None,
    configured_host: str | None = None,
) -> dict[str, Any]:
    """Report project, host, hooks, transcript, and distill queue health."""

    root = project_root.expanduser().resolve() if project_root is not None else None
    from harness_mem.commands.support import normalize_client_name

    host_hint = configured_host or os.environ.get("HARNESS_MEM_CLIENT")
    host = normalize_client_name(host_hint) if host_hint else "unknown"

    hook_files = (
        collect_hook_file_statuses(root, client=host)
        if root is not None and host != "unknown"
        else ()
    )
    installed_hooks = [hook for hook in hook_files if hook.exists and hook.configured]
    wake_execution = (
        _inspect_hook_execution(
            backend.data_dir,
            project_root=root,
            client=host,
            action="wake-start",
        )
        if root is not None and host != "unknown"
        else _unknown_hook_execution()
    )
    maintenance_execution = (
        _inspect_hook_execution(
            backend.data_dir,
            project_root=root,
            client=host,
            action="post-turn-maintenance",
        )
        if root is not None and host != "unknown"
        else _unknown_hook_execution()
    )
    hook_actions = {
        "wake_start": wake_execution,
        "post_turn_maintenance": maintenance_execution,
    }
    hook_freshness = _combined_hook_freshness(hook_actions)
    session_pair_status = _session_pair_status(host, hook_actions)
    current_success_times = [
        str(action["last_success_at"])
        for action in hook_actions.values()
        if action.get("config_match") and action.get("last_success_at")
    ]
    hook_last_success_at = max(current_success_times, default=None)
    if host == "unknown" or root is None:
        hooks_status = "unknown"
    elif not hook_files:
        hooks_status = "unsupported"
    elif len(installed_hooks) == len(hook_files):
        if host != "codex":
            hooks_status = "ok"
        elif any(
            action["receipt_status"] in {"invalid", "config_mismatch"}
            for action in hook_actions.values()
        ):
            hooks_status = "invalid"
        elif hook_freshness == "fresh" and session_pair_status == "matched":
            hooks_status = "ok"
        elif hook_freshness == "never":
            hooks_status = "review_required"
        else:
            hooks_status = "degraded"
    else:
        hooks_status = "missing"

    sources = backend.transcript_store.list_sources(
        project_name=project_name,
        limit=100000,
    )
    observations = await backend.verbatim_store.list(
        project_name=project_name,
        limit=100000,
    )
    transcript_clients = sorted(
        {
            *[str(source.client) for source in sources if source.client],
            *[
                str(observation.client)
                for observation in observations
                if observation.client
            ],
        }
    )
    host_sources = sum(1 for item in sources if item.client == host)
    host_observations = sum(1 for item in observations if item.client == host)
    adapter_available = host in AdapterRegistry.list()
    if sources:
        transcript_status = "synced"
    elif observations:
        transcript_status = "observed"
    elif host == "unknown":
        transcript_status = "unknown"
    elif adapter_available:
        transcript_status = "ready"
    else:
        transcript_status = "unsupported"

    lossless_queued = []
    for status in ("queued", "retryable", "reviewing"):
        lossless_queued.extend(
            backend.transcript_store.list_distill_jobs(
                project_name=project_name,
                status=status,
                limit=100,
            )
        )
    legacy_audit_only = backend.reflection_job_store.list(
        project_name=project_name,
        status="needs_distill",
        kind="reflection",
        limit=100,
    )
    queued = lossless_queued
    lossless_processing = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        status="processing",
        limit=100,
    )
    processing = lossless_processing
    from harness_mem.commands.distill_lifecycle import distill_drainer_metrics

    distill_config = load_merged_config(root) if root is not None else MergedConfig()
    drainer = distill_drainer_metrics(
        backend,
        project_name=project_name,
        daily_job_budget=distill_config.distill_auto_daily_job_budget,
    )
    distill_status = "processing" if processing else str(drainer["state"])
    autonomous_receipt = None
    if root is not None:
        from harness_mem.autonomous.worker import read_autonomous_receipt

        autonomous_receipt = read_autonomous_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=root,
        )
    all_distill_jobs = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100_000,
    )
    autonomous_outcome: dict[str, Any] = {}
    if root is not None:
        from harness_mem.outcome_probe import inspect_autonomous_outcome

        autonomous_outcome = inspect_autonomous_outcome(
            backend.data_dir,
            project_name=project_name,
            project_root=root,
            jobs=all_distill_jobs,
        )
    auth_status = background_status(distill_config, client=host)
    health_card = _build_autonomous_health_card(
        authorization=auth_status,
        autonomous=autonomous_outcome,
        jobs=all_distill_jobs,
        drainer=drainer,
        hooks_configured=bool(hook_files) and len(installed_hooks) == len(hook_files),
        post_turn_last_success_at=maintenance_execution.get("last_success_at"),
    )
    project_status = "ok" if root is not None else "unknown"
    latest_source = max(sources, key=lambda item: item.updated_at) if sources else None
    completed_chunks = sum(
        getattr(job, "completed_chunk_count", 0) for job in [*queued, *processing]
    )
    expected_chunks = sum(
        getattr(job, "expected_chunk_count", 0) for job in [*queued, *processing]
    )
    missing_sources = [source for source in sources if source.status == "missing"]
    failed_sources = [source for source in sources if source.status == "failed"]
    partial_sources = [source for source in sources if source.coverage != "complete"]
    frontiers = backend.transcript_store.list_scan_frontiers(project_name=project_name)
    retry_source_count = sum(len(frontier.retry_sources) for frontier in frontiers)
    summary = (
        f"project={project_status} | host={host} | "
        f"hooks={hooks_status} ({len(installed_hooks)}/{len(hook_files)}) | "
        f"transcript={transcript_status} ({len(sources)} sessions, {len(missing_sources)} missing, {retry_source_count} retrying) | "
        f"distill={distill_status} ({len(queued)} queued, {len(processing)} processing, {drainer['parked']} parked)"
    )
    return {
        "summary": summary,
        "project": {
            "status": project_status,
            "name": project_name,
            "root": str(root) if root is not None else None,
        },
        "host": {"status": "ok" if host != "unknown" else "unknown", "client": host},
        "hooks": {
            "status": hooks_status,
            "installed": len(installed_hooks),
            "expected": len(hook_files),
            "files": [str(hook.path) for hook in hook_files if hook.exists],
            "freshness_threshold_seconds": HOOK_RECEIPT_FRESHNESS_SECONDS,
            "freshness": hook_freshness,
            "last_success_at": hook_last_success_at,
            "wake_verified": wake_execution["freshness"] == "fresh",
            "maintenance_verified": maintenance_execution["freshness"] == "fresh",
            "session_pair_status": session_pair_status,
            "lifecycle_verified": session_pair_status in {"matched", "not_required"},
            "actions": hook_actions,
            "action_required": _hook_action_required(hooks_status),
        },
        "transcript": {
            "status": transcript_status,
            "session_count": len(sources),
            "observation_count": len(observations),
            "host_session_count": host_sources,
            "host_observation_count": host_observations,
            "clients": transcript_clients,
            "adapter_available": adapter_available,
            "latest_source_revision": (
                latest_source.source_revision if latest_source is not None else None
            ),
            "latest_source_coverage": (
                latest_source.coverage if latest_source is not None else None
            ),
            "missing_source_count": len(missing_sources),
            "failed_source_count": len(failed_sources),
            "partial_source_count": len(partial_sources),
            "retry_source_count": retry_source_count,
        },
        "pending_distill": {
            "status": distill_status,
            "queued": len(queued),
            "processing": len(processing),
            "completed_chunks": completed_chunks,
            "expected_chunks": expected_chunks,
            "legacy_audit_only": len(legacy_audit_only),
            "parked": drainer["parked"],
            "retry_backoff": drainer["retry_backoff"],
            "offered_today": drainer["offered_today"],
            "daily_job_budget": drainer["daily_job_budget"],
            "daily_budget_remaining": drainer["daily_budget_remaining"],
            "completed_24h": drainer["completed_24h"],
            "completed_7d": drainer["completed_7d"],
            "promoted_7d": drainer["promoted_7d"],
            "no_candidate_7d": drainer["no_candidate_7d"],
            "legacy_unknown_7d": drainer["legacy_unknown_7d"],
            "source_cleanup_partial_failure": drainer["source_cleanup_partial_failure"],
            "source_cleanup_unsupported": drainer["source_cleanup_unsupported"],
            "throughput_per_day_7d": drainer["throughput_per_day_7d"],
            "oldest_parked_age_hours": drainer["oldest_parked_age_hours"],
            "recent_lane_selected": drainer["recent_lane_selected"],
            "oldest_lane_selected": drainer["oldest_lane_selected"],
            "pending_total": drainer["pending_total"],
            "queue_preview": drainer["queue_preview"],
            "stuck_reasons": drainer["stuck_reasons"],
            "drain_estimate": drainer["drain_estimate"],
            "agent_required": drainer["agent_required"],
            "background_semantic_processing": drainer["background_semantic_processing"],
            "autonomous_active": drainer["autonomous_active"],
            "last_semantic_success_at": (
                autonomous_outcome.get("last_semantic_success_at")
                or drainer["last_semantic_success_at"]
            ),
            "last_job_completed_at": autonomous_outcome.get(
                "last_job_completed_at"
            ),
            "last_note_materialized_at": autonomous_outcome.get(
                "last_note_materialized_at"
            ),
            "autonomous_state": (
                autonomous_receipt.get("state") if autonomous_receipt else "not_run"
            ),
        },
        "health_card": health_card,
    }


def _build_autonomous_health_card(
    *,
    authorization: Any,
    autonomous: dict[str, Any],
    jobs: list[Any],
    drainer: dict[str, Any],
    hooks_configured: bool,
    post_turn_last_success_at: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one idle-safe, user-facing autonomous health decision."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(hours=24)
    recent_failures = [
        job
        for job in jobs
        if job.review_execution_source == "autonomous_worker"
        and job.status in {"retryable", "failed"}
        and bool(job.error)
        and job.updated_at.astimezone(timezone.utc) >= cutoff
    ]
    retry_backoff = max(0, int(drainer.get("retry_backoff") or 0))
    recovery_exhausted = max(0, int(drainer.get("recovery_exhausted") or 0))
    stalled_hours = max(
        0.0,
        float(drainer.get("oldest_stalled_age_hours") or 0.0),
    )
    queue_overdue = retry_backoff + recovery_exhausted
    if stalled_hours >= _DISTILL_STALLED_HOURS_WARNING:
        queue_overdue += 1

    provider = dict(autonomous.get("provider") or {})
    total_tokens = int(provider.get("total_tokens") or 0)
    provider_seconds = float(provider.get("duration_seconds") or 0.0)
    semantic_success_at = _parse_health_timestamp(
        autonomous.get("last_semantic_success_at")
    )
    post_turn_at = _parse_health_timestamp(post_turn_last_success_at)
    semantic_success_age_hours = (
        round(max(0.0, (current - semantic_success_at).total_seconds() / 3600), 2)
        if semantic_success_at is not None
        else None
    )
    post_turn_is_recent = bool(
        post_turn_at is not None
        and current - post_turn_at <= timedelta(hours=_SEMANTIC_SUCCESS_STALE_HOURS)
    )
    progress_expected = bool(
        int(drainer.get("active") or 0) > 0
        and int(drainer.get("daily_budget_remaining") or 0) > 0
        and drainer.get("state") != "daily_budget_exhausted"
        and post_turn_is_recent
    )
    semantic_success_freshness = (
        "not_run"
        if not autonomous.get("receipt_exists")
        else "invalid"
        if autonomous.get("last_semantic_success_at") and semantic_success_at is None
        else "stale"
        if progress_expected
        and (
            semantic_success_age_hours is None
            or semantic_success_age_hours >= _SEMANTIC_SUCCESS_STALE_HOURS
        )
        else "current"
    )
    issue_codes: list[str] = []
    severe_codes: set[str] = set()

    if not getattr(authorization, "ready", False):
        status = "disabled"
    else:
        if not hooks_configured:
            issue_codes.append("hooks_not_configured")
            severe_codes.add("hooks_not_configured")
        if not autonomous.get("receipt_exists"):
            if post_turn_last_success_at:
                issue_codes.append("autonomous_receipt_missing")
                severe_codes.add("autonomous_receipt_missing")
        elif not autonomous.get("lifecycle_verified"):
            for code, field in (
                ("job_binding_invalid", "batch_binding_valid"),
                ("runtime_mismatch", "runtime_current"),
                ("config_mismatch", "config_current"),
                ("provider_unverified", "provider_isolated"),
                ("provider_metrics_missing", "provider_metrics_bound"),
                ("note_unverified", "note_verified"),
            ):
                if autonomous.get(field) is not True:
                    issue_codes.append(code)
                    severe_codes.add(code)
            if autonomous.get("state") not in {"succeeded", "partial"}:
                issue_codes.append("latest_batch_failed")
                severe_codes.add("latest_batch_failed")
        if (
            autonomous.get("lifecycle_verified")
            and autonomous.get("state") in {"deferred", "busy"}
        ):
            issue_codes.append("latest_batch_failed")
        if autonomous.get("state") == "partial":
            issue_codes.append("latest_batch_partial")
        if recent_failures:
            issue_codes.append("autonomous_failures_24h")
        if queue_overdue:
            issue_codes.append("queue_overdue")
        if total_tokens > _AUTONOMOUS_TOKEN_WARNING:
            issue_codes.append("token_regression")
        if provider_seconds > _AUTONOMOUS_SECONDS_WARNING:
            issue_codes.append("latency_regression")
        if semantic_success_freshness == "stale":
            issue_codes.append("semantic_success_stale")
        elif semantic_success_freshness == "invalid":
            issue_codes.append("semantic_success_time_invalid")
            severe_codes.add("semantic_success_time_invalid")

        if severe_codes:
            status = "unhealthy"
        elif issue_codes:
            status = "attention"
        elif autonomous.get("receipt_exists"):
            status = "healthy"
        else:
            status = "not_run"

    alert = status in {"attention", "unhealthy"}
    label = {
        "healthy": "Healthy",
        "attention": "Attention",
        "unhealthy": "Unhealthy",
        "disabled": "Disabled",
        "not_run": "Not run yet",
    }[status]
    return {
        "schema_version": "harness_mem.health_card.v1",
        "status": status,
        "alert": alert,
        "summary": f"harness-mem: {label}",
        "checked_at": current.isoformat(),
        "authorization": {
            "ready": bool(getattr(authorization, "ready", False)),
            "on": bool(getattr(authorization, "on", False)),
            "reason": getattr(authorization, "reason", None),
            "selected_cli": getattr(authorization, "selected_cli", None),
            "message": background_reason_message(
                str(getattr(authorization, "reason", "") or "")
            ),
            "legacy_off": bool(getattr(authorization, "legacy_off", False)),
        },
        "chain_verified": bool(autonomous.get("lifecycle_verified")),
        "last_run": {
            "at": autonomous.get("last_semantic_success_at"),
            "age_hours": semantic_success_age_hours,
            "freshness": semantic_success_freshness,
            "tokens": total_tokens or None,
            "seconds": provider_seconds or None,
            "model": provider.get("model"),
            "trigger_id": autonomous.get("trigger_id"),
            "job_id": autonomous.get("job_id"),
            "note_path": dict(autonomous.get("note") or {}).get("path"),
        },
        "queue": {
            "active": int(drainer.get("active") or 0),
            "parked": int(drainer.get("parked") or 0),
            "retry_backoff": retry_backoff,
            "overdue": queue_overdue,
        },
        "failures_24h": len(recent_failures),
        "issue_codes": list(dict.fromkeys(issue_codes)),
        "thresholds": {
            "tokens": _AUTONOMOUS_TOKEN_WARNING,
            "seconds": _AUTONOMOUS_SECONDS_WARNING,
            "stalled_hours": _DISTILL_STALLED_HOURS_WARNING,
            "semantic_success_stale_hours": _SEMANTIC_SUCCESS_STALE_HOURS,
        },
    }


def _parse_health_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unknown_hook_execution() -> dict[str, Any]:
    return {
        "freshness": "never",
        "receipt_status": "missing",
        "last_success_at": None,
        "age_seconds": None,
        "config_match": False,
        "trigger_id": None,
    }


def _inspect_hook_execution(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    action: str,
) -> dict[str, Any]:
    health = inspect_hook_execution_receipt(
        data_dir,
        project_root=project_root,
        client=client,
        action=action,
    )
    receipt = read_hook_execution_receipt(
        data_dir,
        project_root=project_root,
        client=client,
        action=action,
    )
    trigger_id = receipt.get("trigger_id") if receipt is not None else None
    return {**health, "trigger_id": trigger_id}


def _session_pair_status(
    host: str,
    actions: dict[str, dict[str, Any]],
) -> str:
    if host != "codex":
        return "not_required"
    wake = actions["wake_start"]
    maintenance = actions["post_turn_maintenance"]
    if wake.get("freshness") != "fresh" or maintenance.get("freshness") != "fresh":
        return "incomplete"
    wake_session = wake.get("trigger_id")
    maintenance_session = maintenance.get("trigger_id")
    if not isinstance(wake_session, str) or not wake_session:
        return "missing_session_id"
    if not isinstance(maintenance_session, str) or not maintenance_session:
        return "missing_session_id"
    return "matched" if wake_session == maintenance_session else "mismatched"


def _combined_hook_freshness(actions: dict[str, dict[str, Any]]) -> str:
    freshness = [str(action.get("freshness") or "never") for action in actions.values()]
    if freshness and all(value == "fresh" for value in freshness):
        return "fresh"
    if freshness and all(value == "never" for value in freshness):
        return "never"
    return "stale"


def _hook_action_required(status: str) -> str | None:
    if status == "review_required":
        return "Open Codex Settings > Hooks, trust this project's hooks, then start a new task."
    if status == "degraded":
        return (
            "Codex hooks lack fresh success proof for one or more lifecycle actions; "
            "review Hooks, start a new task, and complete one turn."
        )
    if status == "invalid":
        return (
            "The current hook configuration does not match its last success receipt; "
            "review and trust the current Hooks definition, then start a new task."
        )
    return None


__all__ = ["build_integration_health"]
