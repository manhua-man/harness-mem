from __future__ import annotations

import json

from harness_mem.commands import token_estimator
from harness_mem.mcp.response_views import (
    project_status_decision_fingerprint,
    render_project_status,
)


def _status_snapshot() -> dict:
    high_output_calls = [
        {
            "timestamp": f"2026-07-17T00:{index:02d}:00+00:00",
            "tool_name": "get_project_status",
            "output_tokens": 8000 + index,
            "hints": ["request compact status"],
        }
        for index in range(40)
    ]
    return {
        "success": True,
        "project_name": "demo",
        "project_root": "F:/demo",
        "active_project": "demo",
        "integration_bootstrap": {
            "attempted": True,
            "host_client": "codex",
            "hooks_status": "existing",
        },
        "truth_runtime_state": "canonical",
        "truth_runtime_error": None,
        "truth_runtime_recovery_hint": None,
        "observation_count": 207,
        "memory_entry_count": 4,
        "task_handoff_count": 1,
        "confirmed_rule_count": 3,
        "pending_candidate_count": 2,
        "temporal_summary": {"historical_total": 1, "superseded_total": 1},
        "retrieval_profiles": {
            "active": "light",
            "configured": None,
            "source": "default",
            "suggested": "quality",
            "available": [{"name": "light", "summary": "x" * 500}],
        },
        "runtime_versions": {"runtime_version": "0.8.24"},
        "job_health": {"dream": {"failure_count": 0, "retryable_count": 0}},
        "retrieval_health": {
            "window_days": 7,
            "quality_scorecard": {
                "assessment": "poor_feedback",
                "surfaced": 12,
                "abstained": 4,
                "stale_excluded": 2,
                "conflict_excluded": 1,
                "excluded_total": 3,
                "used": 3,
                "ignored": 2,
                "misleading": 1,
                "insufficient_feedback": False,
                "explanation": "full detail",
            },
            "surfaces": [
                {
                    "surface": "status",
                    "call_count": 40,
                    "high_output_calls": 40,
                }
            ],
            "recent_high_output_calls": high_output_calls,
            "top_opportunities": [{"kind": "compact_status", "count": 40}],
        },
        "cost_budget": {
            "policy": {
                "policy_version": "cost-budget-v3.4.4",
                "budgets": {"status": 1200, "distill": 3000},
                "advisory_only": True,
            },
            "summary": {
                "total_calls": 100,
                "total_output_tokens": 800000,
                "high_output_calls": 40,
                "surface_count": 6,
            },
            "recent_high_output_calls": high_output_calls,
            "top_opportunities": [{"kind": "compact_status", "count": 40}],
        },
        "install_drift": {
            "runtime_version": "0.8.24",
            "wire_format_version": "hm-wire-v3.5",
            "has_drift": False,
            "issues": [],
            "surfaces": {"skill": {"text": "x" * 4000}},
        },
        "phase": "ready",
        "suggested_slash": "/hm:wake",
        "reason": "Project memory is available for wake-up context.",
        "repair_hint": "/hm:review",
        "repair_reason": "Pending candidates remain.",
        "why_this_result": "Project is ready.",
        "next_actions": [
            {"label": "wake", "surface": "/hm:wake", "reason": "Resume context."},
            {"label": "review", "surface": "/hm:review", "reason": "Review pending."},
        ],
        "degraded_reason": None,
        "drilldown_hints": [{"why": "legacy full hint"}],
        "guided_flow": {
            "flow_id": "daily-memory-loop",
            "version": "5.13",
            "phase": "ready",
            "current_step_id": "wake",
            "why": "Memory is ready.",
            "steps": [
                {
                    "step_id": "wake",
                    "entry": 'wake(project_name="demo")',
                    "description": "x" * 1000,
                }
            ],
        },
        "integration_health": {
            "summary": "project=ok | host=codex | hooks=ok",
            "project": {"status": "ok", "name": "demo", "root": "F:/demo"},
            "host": {"status": "ok", "client": "codex"},
            "hooks": {
                "status": "ok",
                "installed": 1,
                "expected": 1,
                "files": ["F:/demo/.codex/hooks.json"],
                "wake_verified": True,
                "maintenance_verified": True,
                "action_required": None,
            },
            "transcript": {
                "status": "synced",
                "session_count": 208,
                "observation_count": 207,
                "missing_source_count": 0,
                "failed_source_count": 0,
                "retry_source_count": 0,
                "latest_source_revision": "sha256:" + "a" * 64,
            },
            "pending_distill": {
                "status": "queued",
                "queued": 2,
                "processing": 0,
                "completed_chunks": 0,
                "expected_chunks": 452,
                "pending_total": 2,
                "stuck_reasons": [
                    {"code": "zero_7d_throughput", "action": "complete one"}
                ],
                "drain_estimate": {
                    "status": "unavailable",
                    "estimated_calendar_days": None,
                    "reason": "zero_7d_throughput",
                },
            },
        },
    }


def test_compact_status_preserves_decisions_and_stays_within_budget() -> None:
    snapshot = _status_snapshot()
    compact = render_project_status(snapshot, detail_level="compact")
    full = render_project_status(snapshot, detail_level="full")

    assert project_status_decision_fingerprint(compact) == (
        project_status_decision_fingerprint(full)
    )
    payload = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    assert token_estimator.count_tokens(payload) <= 1200
    assert compact["retrieval_health"]["high_output_calls"] == 40
    assert compact["retrieval_health"]["quality_scorecard"] == {
        "assessment": "poor_feedback",
        "surfaced": 12,
        "abstained": 4,
        "stale_excluded": 2,
        "conflict_excluded": 1,
        "excluded_total": 3,
        "used": 3,
        "ignored": 2,
        "misleading": 1,
        "insufficient_feedback": False,
    }
    assert "recent_high_output_calls" not in compact["retrieval_health"]
    assert "recent_high_output_calls" not in compact["cost_budget"]


def test_compact_status_exposes_exact_full_drilldown() -> None:
    compact = render_project_status(_status_snapshot(), detail_level="compact")

    assert compact["drilldown_hints"] == [
        {
            "tool": "get_project_status",
            "arguments": {
                "project_root": "F:/demo",
                "host_client": "codex",
                "detail_level": "full",
                "project_name": "demo",
            },
            "why": "Request full diagnostics only when compact status needs investigation.",
        }
    ]


def test_full_status_keeps_complete_diagnostics() -> None:
    snapshot = _status_snapshot()
    full = render_project_status(snapshot, detail_level="full")

    assert full["detail_level"] == "full"
    assert len(full["cost_budget"]["recent_high_output_calls"]) == 40
    assert full["install_drift"]["surfaces"]["skill"]["text"] == "x" * 4000
