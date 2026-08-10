"""Compact and full MCP response views derived from one runtime snapshot."""

from __future__ import annotations

from typing import Any, Mapping


STATUS_CONTRACT_VERSION = "project-status-v4"
STATUS_DETAIL_LEVELS = frozenset({"compact", "full"})


def status_triage_hints(counts: Mapping[str, Any]) -> dict[str, Any]:
    """Select the daily status phase from the shared project counts."""

    distill = dict(counts.get("pending_distill") or {})
    pending_distill = int(distill.get("pending_total", 0) or 0)
    if pending_distill > 0:
        return {
            "phase": "needs-distill",
            "suggested_slash": "/hm:distill",
            "reason": f"{pending_distill} captured sessions are waiting for distill.",
            "repair_hint": None,
            "repair_reason": None,
        }

    if (
        int(counts.get("observation_count", 0) or 0) == 0
        and int(counts.get("durable_truth_count", 0) or 0) == 0
        and int(counts.get("task_handoff_count", 0) or 0) == 0
        and int(counts.get("confirmed_rule_count", 0) or 0) == 0
    ):
        return {
            "phase": "awaiting-capture",
            "suggested_slash": "/hm:wake",
            "reason": "No captured evidence or durable memory exists yet.",
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
    distill = dict(counts.get("pending_distill") or {})
    pending_distill = int(distill.get("pending_total", 0) or 0)
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
        degraded_reason = "pending_distill_sessions"
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
            f"{pending_distill} sessions waiting for distill, {pending} pending candidates."
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
        "integration_bootstrap": bootstrap,
        "truth_runtime_state": full.get("truth_runtime_state"),
        "truth_runtime_error": full.get("truth_runtime_error"),
        "truth_runtime_recovery_hint": full.get("truth_runtime_recovery_hint"),
        "degraded_reason": full.get("degraded_reason"),
        "reason": full.get("reason"),
        "repair_hint": full.get("repair_hint"),
        "repair_reason": full.get("repair_reason"),
        "suggested_slash": full.get("suggested_slash"),
        "temporal_summary": _compact_temporal_summary(
            full.get("temporal_summary")
        ),
        "retrieval_profiles": _compact_retrieval_profiles(
            full.get("retrieval_profiles")
        ),
        "runtime_versions": _compact_runtime_versions(full.get("runtime_versions")),
        "job_health": _compact_job_health(full.get("job_health")),
        "retrieval_health": _compact_retrieval_health(
            full.get("retrieval_health")
        ),
        "memory_funnel": _compact_memory_funnel(full.get("memory_funnel")),
        "cost_budget": _compact_cost_budget(full.get("cost_budget")),
        "install_drift": _compact_install_drift(full.get("install_drift")),
        "integration_health": _compact_integration_health(
            full.get("integration_health")
        ),
        "pending_distill": _compact_pending_distill(full.get("pending_distill")),
        "guided_flow": compact_guided_flow,
        "why_this_result": _compact_status_reason(full),
        "next_actions": _compact_next_actions(full.get("next_actions")),
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
    return _prune_compact(compact)


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
        "next_actions": _next_action_fingerprint(payload.get("next_actions")),
        "pending_distill": _compact_pending_distill(payload.get("pending_distill")),
        "memory_funnel": _compact_memory_funnel(payload.get("memory_funnel")),
    }


def _compact_retrieval_profiles(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    return {
        "active": payload.get("active"),
        "configured": payload.get("configured"),
        "source": payload.get("source"),
        "suggested": payload.get("suggested"),
    }


def _compact_temporal_summary(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    historical_total = int(payload.get("historical_total", 0) or 0)
    superseded_total = int(payload.get("superseded_total", 0) or 0)
    if historical_total == 0 and superseded_total == 0:
        return {}
    return {
        "historical_total": historical_total,
        "superseded_total": superseded_total,
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
    if not any(
        (
            int(dream.get("failure_count", 0) or 0),
            int(dream.get("retryable_count", 0) or 0),
            dream.get("latest_error"),
        )
    ):
        return {}
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
    scorecard = dict(payload.get("quality_scorecard") or {})
    return {
        "window_days": payload.get("window_days"),
        "surface_count": len(surfaces),
        "call_count": sum(int(row.get("call_count", 0) or 0) for row in surfaces),
        "high_output_calls": sum(
            int(row.get("high_output_calls", 0) or 0) for row in surfaces
        ),
        "quality_scorecard": {
            "assessment": scorecard.get("assessment"),
            "surfaced": scorecard.get("surfaced"),
            "abstained": scorecard.get("abstained"),
            "stale_excluded": scorecard.get("stale_excluded"),
            "conflict_excluded": scorecard.get("conflict_excluded"),
            "excluded_total": scorecard.get("excluded_total"),
            "used": scorecard.get("used"),
            "ignored": scorecard.get("ignored"),
            "misleading": scorecard.get("misleading"),
            "missing_feedback": scorecard.get("missing_feedback"),
            "insufficient_feedback": scorecard.get("insufficient_feedback"),
        },
        "top_opportunities": list(payload.get("top_opportunities") or [])[:3],
    }


def _compact_memory_funnel(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    stages = dict(payload.get("distinct_jobs") or {})
    feedback = dict(payload.get("retrieval_feedback") or {})
    if not stages and not feedback:
        return {}
    return {
        "distinct_jobs": {
            key: int(stages.get(key) or 0)
            for key in (
                "offered",
                "claimed",
                "checkpointed",
                "finalized",
                "searchable",
                "surfaced",
            )
        },
        "retrieval_feedback": {
            key: int(feedback.get(key) or 0)
            for key in (
                "surfaced",
                "used",
                "ignored",
                "misleading",
                "missing_feedback",
            )
        },
    }


def _compact_cost_budget(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    policy = dict(payload.get("policy") or {})
    budgets = dict(policy.get("budgets") or {})
    return {
        "status_budget_tokens": budgets.get("status"),
        "distill_budget_tokens": budgets.get("distill"),
        "high_output_calls": dict(payload.get("summary") or {}).get(
            "high_output_calls"
        ),
        "top_opportunities": list(payload.get("top_opportunities") or [])[:2],
    }


def _compact_install_drift(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    issues = list(payload.get("issues") or [])
    compact = {
        "runtime_version": payload.get("runtime_version"),
        "wire_format_version": payload.get("wire_format_version"),
        "has_drift": bool(payload.get("has_drift")),
        "issue_count": len(issues),
        "issues": issues[:3],
    }
    if not compact["has_drift"]:
        return {"has_drift": False}
    return compact


def _compact_integration_health(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    project = dict(payload.get("project") or {})
    host = dict(payload.get("host") or {})
    hooks = dict(payload.get("hooks") or {})
    transcript = dict(payload.get("transcript") or {})
    distill = dict(payload.get("pending_distill") or {})
    compact_hooks = {
        "status": hooks.get("status"),
        "action_required": hooks.get("action_required"),
    }
    if hooks.get("status") != "ok":
        compact_hooks.update(
            {
                "freshness": hooks.get("freshness"),
                "last_success_at": hooks.get("last_success_at"),
                "wake_verified": hooks.get("wake_verified"),
                "maintenance_verified": hooks.get("maintenance_verified"),
            }
        )
    return {
        "project": {
            "status": project.get("status"),
        },
        "host": {
            "status": host.get("status"),
            "client": host.get("client"),
        },
        "hooks": compact_hooks,
        "transcript": {
            "status": transcript.get("status"),
            "session_count": transcript.get("session_count"),
            "missing_source_count": transcript.get("missing_source_count"),
            "failed_source_count": transcript.get("failed_source_count"),
            "retry_source_count": transcript.get("retry_source_count"),
        },
        "pending_distill": {
            "status": distill.get("status"),
            "throughput_per_day_7d": distill.get("throughput_per_day_7d"),
            "stuck_reason_codes": [
                reason.get("code")
                for reason in list(distill.get("stuck_reasons") or [])[:3]
                if isinstance(reason, Mapping)
            ],
            "drain_estimate": {
                "status": dict(distill.get("drain_estimate") or {}).get("status"),
                "estimated_calendar_days": dict(
                    distill.get("drain_estimate") or {}
                ).get("estimated_calendar_days"),
            },
            "agent_required": distill.get("agent_required"),
        },
    }


def _compact_next_actions(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "label": row.get("label"),
            "surface": row.get("surface"),
        }
        for row in list(value or [])
        if isinstance(row, Mapping)
    ]


def _next_action_fingerprint(value: Any) -> list[dict[str, Any]]:
    return _compact_next_actions(value)


def _compact_status_reason(payload: Mapping[str, Any]) -> str:
    pending = _compact_pending_distill(payload.get("pending_distill"))
    return (
        f"{payload.get('phase')}: {int(pending.get('pending_total') or 0)} distill, "
        f"{int(payload.get('pending_candidate_count', 0) or 0)} candidates."
    )


def _prune_compact(value: Any) -> Any:
    """Drop empty diagnostics from compact views while preserving false/zero."""

    if isinstance(value, Mapping):
        result = {
            key: _prune_compact(item)
            for key, item in value.items()
            if item is not None
        }
        return {
            key: item
            for key, item in result.items()
            if item not in ({}, [])
        }
    if isinstance(value, list):
        return [_prune_compact(item) for item in value]
    return value


def _compact_pending_distill(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    admission = dict(
        payload.get("evidence_admission_7d")
        or payload.get("evidence_admission_attention_7d")
        or {}
    )
    return {
        "state": payload.get("state"),
        "active": payload.get("active"),
        "parked": payload.get("parked"),
        "retry_backoff": payload.get("retry_backoff"),
        "pending_total": payload.get("pending_total"),
        "completed_7d": payload.get("completed_7d"),
        "promoted_7d": payload.get("promoted_7d"),
        "no_candidate_7d": payload.get("no_candidate_7d"),
        "legacy_unknown_7d": payload.get("legacy_unknown_7d"),
        "evidence_admission_attention_7d": {
            key: int(admission.get(key) or 0)
            for key in ("unverified_blocked", "contradicted")
            if int(admission.get(key) or 0) > 0
        },
        "source_cleanup_partial_failure": payload.get(
            "source_cleanup_partial_failure"
        ),
        "source_cleanup_unsupported": payload.get("source_cleanup_unsupported"),
    }


__all__ = [
    "STATUS_CONTRACT_VERSION",
    "STATUS_DETAIL_LEVELS",
    "build_status_dx_metadata",
    "project_status_decision_fingerprint",
    "render_project_status",
    "status_triage_hints",
]
