from __future__ import annotations

import json

from harness_mem.commands import token_estimator
from harness_mem.guided_flow import build_guided_flow
from harness_mem.mcp.response_views import (
    project_status_decision_fingerprint,
    render_project_status,
    status_triage_hints,
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
        "pending_distill": {
            "state": "waiting_for_agent",
            "active": 2,
            "parked": 0,
            "retry_backoff": 0,
            "pending_total": 2,
            "completed_7d": 8,
            "promoted_7d": 5,
            "no_candidate_7d": 3,
            "legacy_unknown_7d": 0,
            "evidence_admission_7d": {
                "repository_verified": 4,
                "user_stated": 2,
                "unverified_blocked": 1,
                "contradicted": 1,
                "legacy_or_unknown": 0,
            },
        },
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
        "memory_funnel": {
            "schema_version": "harness_mem.memory_funnel.v1",
            "distill_window_days": 7,
            "retrieval_window_days": 7,
            "distinct_jobs": {
                "captured": 20,
                "offered": 15,
                "claimed": 14,
                "checkpointed": 12,
                "verified": 10,
                "finalized": 10,
                "promoted": 6,
                "searchable": 6,
                "surfaced": 4,
            },
            "finalized": {
                "total": 10,
                "promoted": 6,
                "no_candidate": 4,
                "unsettled": 0,
                "successful_terminal": 10,
            },
            "retrieval_feedback": {
                "surfaced": 8,
                "used": 3,
                "ignored": 1,
                "misleading": 1,
                "missing_feedback": 3,
                "legacy_uncorrelated": 2,
            },
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
            {
                "label": "run_suggested_entry",
                "surface": "/hm:distill",
                "reason": "Captured sessions are waiting for distill before the next wake.",
            },
            {
                "label": "review_pending_when_needed",
                "surface": "/hm:review",
                "reason": "Review only when correcting or rechecking candidates.",
            },
            {
                "label": "search_before_task",
                "surface": '/hm:search "<topic>"',
                "reason": "Search narrows the wake context to the current task.",
            },
            {
                "label": "consider_retrieval_quality_profile",
                "surface": "operator_profile_edit",
                "reason": "The quality profile is available but remains opt-in.",
            },
        ],
        "degraded_reason": None,
        "health_card": {
            "status": "healthy",
            "alert": False,
            "summary": "harness-mem: Healthy",
            "chain_verified": True,
            "last_run": {
                "at": "2026-08-10T12:00:05+00:00",
                "age_hours": 1.5,
                "freshness": "current",
                "tokens": 6001,
                "seconds": 13.48,
                "model": "gpt-test",
                "note_path": "C:/notes/session.md",
            },
            "queue": {
                "active": 1,
                "parked": 199,
                "retry_backoff": 0,
                "overdue": 0,
            },
            "failures_24h": 0,
            "issue_codes": [],
        },
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
                "freshness": "fresh",
                "last_success_at": "2026-08-10T12:00:00+00:00",
                "installed": 1,
                "expected": 1,
                "files": ["F:/demo/.codex/hooks.json"],
                "wake_verified": True,
                "maintenance_verified": True,
                "actions": {
                    "wake_start": {
                        "freshness": "fresh",
                        "last_success_at": "2026-08-10T12:00:00+00:00",
                        "age_seconds": 30,
                        "receipt_status": "current",
                        "config_match": True,
                    },
                    "post_turn_maintenance": {
                        "freshness": "fresh",
                        "last_success_at": "2026-08-10T12:00:05+00:00",
                        "age_seconds": 25,
                        "receipt_status": "current",
                        "config_match": True,
                    },
                },
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
                "evidence_admission_7d": {
                    "repository_verified": 4,
                    "user_stated": 2,
                    "unverified_blocked": 1,
                    "contradicted": 1,
                    "legacy_or_unknown": 0,
                },
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
    assert token_estimator.count_tokens(payload) <= 1000
    assert compact["contract_version"] == "project-status-v4"
    assert "counts" not in compact
    assert "job_health" not in compact
    assert all("reason" not in action for action in compact["next_actions"])
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
    assert compact["pending_distill"]["evidence_admission_attention_7d"] == {
        "unverified_blocked": 1,
        "contradicted": 1,
    }
    assert compact["health_card"] == {
        "status": "healthy",
        "alert": False,
        "chain_verified": True,
        "last_run": {
            "at": "2026-08-10T12:00:05+00:00",
            "tokens": 6001,
            "seconds": 13.48,
        },
        "queue_overdue": 0,
        "failures_24h": 0,
    }
    assert compact["memory_funnel"]["retrieval_feedback"] == {
        "surfaced": 8,
        "used": 3,
        "ignored": 1,
        "misleading": 1,
        "missing_feedback": 3,
    }
    assert "freshness" not in compact["integration_health"]["hooks"]
    assert "last_success_at" not in compact["integration_health"]["hooks"]
    assert "actions" not in compact["integration_health"]["hooks"]


def test_compact_status_keeps_hook_last_success_when_health_is_not_ok() -> None:
    snapshot = _status_snapshot()
    hooks = snapshot["integration_health"]["hooks"]
    hooks["status"] = "degraded"
    hooks["freshness"] = "stale"
    hooks["last_success_at"] = "2026-08-08T12:00:00+00:00"
    hooks["wake_verified"] = False
    hooks["maintenance_verified"] = False
    hooks["action_required"] = "Start a new task and complete one turn."

    compact = render_project_status(snapshot, detail_level="compact")

    assert compact["integration_health"]["hooks"] == {
        "status": "degraded",
        "freshness": "stale",
        "last_success_at": "2026-08-08T12:00:00+00:00",
        "wake_verified": False,
        "maintenance_verified": False,
        "action_required": "Start a new task and complete one turn.",
    }


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


def test_compact_status_keeps_a_bounded_id_free_queue_preview() -> None:
    snapshot = _status_snapshot()
    snapshot["pending_distill"]["queue_preview"] = [
        {
            "project_name": "demo",
            "session_label": f"Codex session captured 2026-07-17T00:0{index}:00+00:00",
            "source_host": "codex",
            "captured_at": f"2026-07-17T00:0{index}:00+00:00",
            "state": "queued_for_agent",
            "progress": {"completed_chunks": 0, "expected_chunks": 3},
            "handler": {"kind": "waiting", "label": "waiting for a Codex Agent"},
        }
        for index in range(4)
    ]

    compact = render_project_status(snapshot, detail_level="compact")

    preview = compact["pending_distill"]["queue_preview"]
    assert len(preview) == 3
    assert preview[0]["project_name"] == "demo"
    assert preview[0]["handler"]["kind"] == "waiting"
    assert "session_id" not in str(preview)
    assert "job_id" not in str(preview)


def test_full_status_keeps_complete_diagnostics() -> None:
    snapshot = _status_snapshot()
    full = render_project_status(snapshot, detail_level="full")

    assert full["detail_level"] == "full"
    assert len(full["cost_budget"]["recent_high_output_calls"]) == 40
    assert full["install_drift"]["surfaces"]["skill"]["text"] == "x" * 4000
    assert full["integration_health"]["project"]["root"] == "F:/demo"
    assert full["next_actions"][0]["reason"].startswith("Captured sessions")


def test_status_triage_uses_distill_jobs_instead_of_observation_count() -> None:
    ready = status_triage_hints(
        {
            "observation_count": 41,
            "memory_entry_count": 0,
            "task_handoff_count": 0,
            "confirmed_rule_count": 0,
            "pending_candidate_count": 0,
            "pending_distill": {"pending_total": 0},
        }
    )
    waiting = status_triage_hints(
        {
            "observation_count": 0,
            "memory_entry_count": 2,
            "task_handoff_count": 0,
            "confirmed_rule_count": 0,
            "pending_candidate_count": 0,
            "pending_distill": {"pending_total": 3},
        }
    )

    assert ready["phase"] == "ready"
    assert waiting["phase"] == "needs-distill"
    assert "3 captured sessions" in waiting["reason"]


def test_empty_project_waits_for_capture_instead_of_claiming_distill_work() -> None:
    triage = status_triage_hints(
        {
            "observation_count": 0,
            "memory_entry_count": 0,
            "task_handoff_count": 0,
            "confirmed_rule_count": 0,
            "pending_candidate_count": 0,
            "pending_distill": {"pending_total": 0},
        }
    )

    assert triage["phase"] == "awaiting-capture"
    assert triage["suggested_slash"] == "/hm:wake"
    guided = build_guided_flow(
        phase=triage["phase"],
        observation_count=0,
        pending_candidate_count=0,
        memory_entry_count=0,
        project_name="demo",
    )
    assert guided["current_step_id"] == "wake"
    assert guided["steps"][0]["entry"] == 'wake(project_name="demo")'
    assert "No captured evidence" in guided["why"]
