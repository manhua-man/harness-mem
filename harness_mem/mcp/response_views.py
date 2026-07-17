"""Compact and full MCP response views derived from one runtime snapshot."""

from __future__ import annotations

from typing import Any, Mapping


STATUS_CONTRACT_VERSION = "project-status-v2"
STATUS_DETAIL_LEVELS = frozenset({"compact", "full"})


def status_triage_hints(counts: Mapping[str, Any]) -> dict[str, Any]:
    """Select the daily status phase from the shared project counts."""

    if counts["observation_count"] == 0:
        return {
            "phase": "needs-distill",
            "suggested_slash": "/hm:distill",
            "reason": "No observations have been ingested for this project yet.",
            "repair_hint": None,
            "repair_reason": None,
        }

    hints: dict[str, Any] = {
        "phase": "ready",
        "suggested_slash": "/hm:wake",
        "reason": "Project memory is available for wake-up context.",
        "repair_hint": None,
        "repair_reason": None,
    }
    if counts["pending_candidate_count"] > 0:
        hints["repair_hint"] = "/hm:review"
        hints["repair_reason"] = (
            "Pending candidates remain; use review only for explicit recheck or correction."
        )
    return hints


def build_status_dx_metadata(
    counts: Mapping[str, Any],
    triage: Mapping[str, Any],
    *,
    project_name: str,
) -> dict[str, Any]:
    """Build model-facing status actions from the shared status snapshot."""

    phase = str(triage.get("phase") or "unknown")
    pending = int(counts.get("pending_candidate_count", 0) or 0)
    next_actions: list[dict[str, str]] = []
    suggested = triage.get("suggested_slash")
    if suggested:
        next_actions.append(
            _action(
                "run_suggested_entry",
                str(suggested),
                str(triage.get("reason") or "Recommended next daily-flow step."),
            )
        )
    if pending > 0:
        next_actions.append(
            _action(
                "review_pending_when_needed",
                "/hm:review",
                "Pending candidates exist; review only when correcting or rechecking candidates.",
            )
        )
    if counts.get("observation_count", 0) and counts.get("memory_entry_count", 0):
        next_actions.append(
            _action(
                "search_before_task",
                '/hm:search "<topic>"',
                "Search narrows the wake context to the current task.",
            )
        )
    temporal_summary = dict(counts.get("temporal_summary") or {})
    historical_total = int(temporal_summary.get("historical_total", 0) or 0)
    superseded_total = int(temporal_summary.get("superseded_total", 0) or 0)
    if historical_total:
        next_actions.append(
            _action(
                "inspect_temporal_history",
                "temporal_query",
                "This project has historical truth; use temporal_query when asking old-state questions.",
            )
        )
    retrieval_profiles = dict(counts.get("retrieval_profiles") or {})
    if retrieval_profiles.get("suggested"):
        next_actions.append(
            _action(
                "consider_retrieval_quality_profile",
                "operator_profile_edit",
                (
                    "retrieval_profile=quality is available as an opt-in component "
                    "profile; status only suggests it and does not enable it automatically."
                ),
            )
        )
    degraded_reason = None
    if phase == "needs-distill":
        degraded_reason = "no_observations_ingested"
    elif (counts.get("retrieval_health") or {}).get("degraded"):
        degraded_reason = "retrieval_health_degraded"
    drilldown_hints: list[dict[str, Any]] = [
        _action(
            "status_counts",
            "get_project_status",
            "Use counts to decide between wake, search, distill, and review.",
        )
    ]
    if historical_total:
        drilldown_hints.append(
            {
                "source_id": None,
                "source_kind": "temporal_summary",
                "read_surface": "mcp.temporal_query",
                "tool": "temporal_query",
                "arguments": {
                    "project_name": project_name,
                    "mode": "history",
                    "limit": 20,
                },
                "why": (
                    f"Project has {historical_total} historical truth records "
                    f"({superseded_total} superseded)."
                ),
            }
        )
    return {
        "why_this_result": (
            f"Project is in phase {phase}: {counts.get('observation_count', 0)} "
            f"observations, {counts.get('memory_entry_count', 0)} memory entries, "
            f"{pending} pending candidates."
        ),
        "next_actions": next_actions,
        "degraded_reason": degraded_reason,
        "drilldown_hints": drilldown_hints,
    }


def _action(label: str, surface: str, reason: str) -> dict[str, str]:
    return {"label": label, "surface": surface, "reason": reason}


def render_project_status(
    payload: Mapping[str, Any],
    *,
    detail_level: str,
) -> dict[str, Any]:
    """Render a project status snapshot without changing its decisions."""

    if detail_level not in STATUS_DETAIL_LEVELS:
        raise ValueError("detail_level must be one of: compact, full")

    full = dict(payload)
    full["contract_version"] = STATUS_CONTRACT_VERSION
    full["detail_level"] = detail_level
    if detail_level == "full" or not bool(full.get("success")):
        return full

    project_name = full.get("project_name")
    project_root = full.get("project_root")
    bootstrap = dict(full.get("integration_bootstrap") or {})
    host_client = bootstrap.get("host_client")
    drilldown_arguments = {
        "project_root": project_root,
        "host_client": host_client,
        "detail_level": "full",
    }
    if project_name:
        drilldown_arguments["project_name"] = project_name

    counts = {
        key: int(full.get(key, 0) or 0)
        for key in (
            "observation_count",
            "memory_entry_count",
            "task_handoff_count",
            "confirmed_rule_count",
            "pending_candidate_count",
        )
    }
    guided_flow = dict(full.get("guided_flow") or {})
    current_step = next(
        (
            step
            for step in guided_flow.get("steps") or []
            if step.get("step_id") == guided_flow.get("current_step_id")
        ),
        None,
    )
    compact_guided_flow = {
        "flow_id": guided_flow.get("flow_id"),
        "version": guided_flow.get("version"),
        "phase": guided_flow.get("phase"),
        "current_step_id": guided_flow.get("current_step_id"),
        "current_entry": current_step.get("entry") if current_step else None,
        "why": guided_flow.get("why"),
    }

    compact = {
        "success": True,
        "contract_version": STATUS_CONTRACT_VERSION,
        "detail_level": "compact",
        "project_name": project_name,
        "project_root": project_root,
        "active_project": full.get("active_project"),
        "phase": full.get("phase"),
        **counts,
        "counts": counts,
        "integration_bootstrap": bootstrap,
        "truth_runtime_state": full.get("truth_runtime_state"),
        "truth_runtime_error": full.get("truth_runtime_error"),
        "truth_runtime_recovery_hint": full.get("truth_runtime_recovery_hint"),
        "degraded_reason": full.get("degraded_reason"),
        "reason": full.get("reason"),
        "repair_hint": full.get("repair_hint"),
        "repair_reason": full.get("repair_reason"),
        "suggested_slash": full.get("suggested_slash"),
        "temporal_summary": dict(full.get("temporal_summary") or {}),
        "retrieval_profiles": _compact_retrieval_profiles(
            full.get("retrieval_profiles")
        ),
        "runtime_versions": _compact_runtime_versions(full.get("runtime_versions")),
        "job_health": _compact_job_health(full.get("job_health")),
        "retrieval_health": _compact_retrieval_health(
            full.get("retrieval_health")
        ),
        "cost_budget": _compact_cost_budget(full.get("cost_budget")),
        "install_drift": _compact_install_drift(full.get("install_drift")),
        "integration_health": _compact_integration_health(
            full.get("integration_health")
        ),
        "guided_flow": compact_guided_flow,
        "why_this_result": full.get("why_this_result"),
        "next_actions": list(full.get("next_actions") or []),
        "details_available": [
            "retrieval_health",
            "cost_budget",
            "install_drift",
            "integration_health",
            "guided_flow",
        ],
        "drilldown_hints": [
            {
                "tool": "get_project_status",
                "arguments": drilldown_arguments,
                "why": "Request full diagnostics only when compact status needs investigation.",
            }
        ],
    }
    return compact


def project_status_decision_fingerprint(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return fields whose meaning must match between compact and full views."""

    return {
        "success": bool(payload.get("success")),
        "project_name": payload.get("project_name"),
        "active_project": payload.get("active_project"),
        "phase": payload.get("phase"),
        "observation_count": int(payload.get("observation_count", 0) or 0),
        "memory_entry_count": int(payload.get("memory_entry_count", 0) or 0),
        "task_handoff_count": int(payload.get("task_handoff_count", 0) or 0),
        "confirmed_rule_count": int(payload.get("confirmed_rule_count", 0) or 0),
        "pending_candidate_count": int(payload.get("pending_candidate_count", 0) or 0),
        "degraded_reason": payload.get("degraded_reason"),
        "suggested_slash": payload.get("suggested_slash"),
        "repair_hint": payload.get("repair_hint"),
        "next_actions": list(payload.get("next_actions") or []),
    }


def _compact_retrieval_profiles(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    return {
        "active": payload.get("active"),
        "configured": payload.get("configured"),
        "source": payload.get("source"),
        "suggested": payload.get("suggested"),
    }


def _compact_runtime_versions(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    return {
        "runtime_version": payload.get("runtime_version"),
        "wire_format_version": payload.get("wire_format_version"),
    }


def _compact_job_health(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    dream = dict(payload.get("dream") or {})
    return {
        "dream": {
            "last_status": dream.get("last_status"),
            "failure_count": dream.get("failure_count"),
            "retryable_count": dream.get("retryable_count"),
            "latest_error": dream.get("latest_error"),
        }
    }


def _compact_retrieval_health(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    surfaces = list(payload.get("surfaces") or [])
    return {
        "window_days": payload.get("window_days"),
        "surface_count": len(surfaces),
        "call_count": sum(int(row.get("call_count", 0) or 0) for row in surfaces),
        "high_output_calls": sum(
            int(row.get("high_output_calls", 0) or 0) for row in surfaces
        ),
        "top_opportunities": list(payload.get("top_opportunities") or [])[:3],
    }


def _compact_cost_budget(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    policy = dict(payload.get("policy") or {})
    budgets = dict(policy.get("budgets") or {})
    return {
        "policy_version": policy.get("policy_version"),
        "status_budget_tokens": budgets.get("status"),
        "distill_budget_tokens": budgets.get("distill"),
        "summary": dict(payload.get("summary") or {}),
        "top_opportunities": list(payload.get("top_opportunities") or [])[:3],
    }


def _compact_install_drift(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    issues = list(payload.get("issues") or [])
    return {
        "runtime_version": payload.get("runtime_version"),
        "wire_format_version": payload.get("wire_format_version"),
        "has_drift": bool(payload.get("has_drift")),
        "issue_count": len(issues),
        "issues": issues[:3],
    }


def _compact_integration_health(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    project = dict(payload.get("project") or {})
    host = dict(payload.get("host") or {})
    hooks = dict(payload.get("hooks") or {})
    transcript = dict(payload.get("transcript") or {})
    distill = dict(payload.get("pending_distill") or {})
    return {
        "summary": payload.get("summary"),
        "project": {
            "status": project.get("status"),
            "name": project.get("name"),
        },
        "host": {
            "status": host.get("status"),
            "client": host.get("client"),
        },
        "hooks": {
            "status": hooks.get("status"),
            "installed": hooks.get("installed"),
            "expected": hooks.get("expected"),
            "wake_verified": hooks.get("wake_verified"),
            "maintenance_verified": hooks.get("maintenance_verified"),
            "action_required": hooks.get("action_required"),
        },
        "transcript": {
            "status": transcript.get("status"),
            "session_count": transcript.get("session_count"),
            "observation_count": transcript.get("observation_count"),
            "missing_source_count": transcript.get("missing_source_count"),
            "failed_source_count": transcript.get("failed_source_count"),
            "retry_source_count": transcript.get("retry_source_count"),
        },
        "pending_distill": {
            "status": distill.get("status"),
            "queued": distill.get("queued"),
            "processing": distill.get("processing"),
            "parked": distill.get("parked"),
            "retry_backoff": distill.get("retry_backoff"),
            "offered_today": distill.get("offered_today"),
            "daily_job_budget": distill.get("daily_job_budget"),
            "throughput_per_day_7d": distill.get("throughput_per_day_7d"),
            "agent_required": distill.get("agent_required"),
        },
    }


__all__ = [
    "STATUS_CONTRACT_VERSION",
    "STATUS_DETAIL_LEVELS",
    "build_status_dx_metadata",
    "project_status_decision_fingerprint",
    "render_project_status",
    "status_triage_hints",
]
