from __future__ import annotations

from harness_mem.mcp.read_wake_handlers import (
    _compact_wake_command_payload,
    _compact_wake_snapshot,
)
from harness_mem.mcp.read_projection import project_wake_snapshot


def test_compact_wake_keeps_one_authoritative_content_tree() -> None:
    answer_ready = {
        "safe_to_answer": True,
        "truth": ["stable fact"],
        "supporting_evidence": [{"source_id": "memory:1"}],
        "drilldown_hints": [{"tool": "search_memory"}],
    }
    snapshot = {
        "context_sufficiency": {"status": "sufficient"},
        "retrieval_plan": {"query": "task"},
        "iterative_retrieval_trace": {"iterations": []},
        "context_plan": {
            "context_sufficiency": {"status": "sufficient"},
            "retrieval_plan": {"query": "task"},
            "iterative_retrieval_trace": {"iterations": []},
            "context_budget": {"total_tokens": 10},
            "wake_packet": {"essential_truth": ["stable fact"]},
            "drilldown_hints": [{"tool": "search_memory"}],
        },
        "wake_packet": {"essential_truth": ["stable fact"]},
        "supporting_evidence": [{"source_id": "memory:1"}],
        "answer_ready_context": answer_ready,
        "drilldown_hints": [{"tool": "search_memory"}],
        "requested_mode": "auto",
        "effective_mode": "hybrid",
        "effective_deep_recall": False,
        "orchestration_actions": [],
    }

    compact = _compact_wake_snapshot(snapshot)

    assert compact["authoritative_context_field"] == "answer_ready_context"
    assert compact["answer_ready_context"] is answer_ready
    assert compact["context_diagnostics"]["context_budget"] == {
        "total_tokens": 10
    }
    for duplicate in (
        "context_plan",
        "wake_packet",
        "supporting_evidence",
        "context_sufficiency",
        "retrieval_plan",
        "iterative_retrieval_trace",
        "drilldown_hints",
    ):
        assert duplicate not in compact


def test_compact_wake_removes_duplicate_cli_render_but_keeps_status() -> None:
    compact = _compact_wake_command_payload(
        {
            "success": True,
            "exit_code": 0,
            "output": "the same stable fact rendered again",
        }
    )

    assert compact == {
        "success": True,
        "exit_code": 0,
        "rendered_output_available_in_full": True,
    }


def test_compact_wake_keeps_failure_output_for_diagnosis() -> None:
    failed = {"success": False, "exit_code": 1, "output": "wake failed"}

    assert _compact_wake_command_payload(failed) == failed


def test_clean_wake_projection_drops_plan_and_audit_fields() -> None:
    projection = project_wake_snapshot(
        {
            "essential_truth": [
                {
                    "summary": "Use the canonical retrieval path.",
                    "source_ids": ["memory-internal-id"],
                    "truth_status": "auto_confirmed",
                }
            ],
            "active_task": [
                {
                    "summary": "Finish the retrieval contract.",
                    "source_ids": ["handoff-internal-id"],
                    "why_included": "active:recent_handoff",
                }
            ],
        }
    )

    assert projection == {
        "long_term_memory": [
            {
                "title": "Project memory",
                "statement": "Use the canonical retrieval path.",
            }
        ],
        "active_context": [
            {
                "title": "Current context",
                "statement": "Finish the retrieval contract.",
            }
        ],
    }
