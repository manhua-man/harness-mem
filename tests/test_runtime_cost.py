from __future__ import annotations

from harness_mem.runtime_cost import analyze_mcp_surface_cost


def _large_result() -> dict:
    return {"output": "token " * 6000}


def test_budget_exceeded_is_not_reported_as_actual_truncation() -> None:
    analysis = analyze_mcp_surface_cost(
        "get_project_status",
        {"detail_level": "full", "budget_tokens": 1200},
        _large_result(),
        duration_ms=10,
    )

    assert analysis["budget_exceeded"] is True
    assert analysis["truncation"]["truncated_by"] is None
    assert analysis["argument_shape"]["detail_level"] == "full"
    assert analysis["argument_shape"]["budget_tokens"] == 1200
    assert "compact_status" in analysis["opportunity_kinds"]


def test_distill_cost_hint_uses_semantic_drilldown_not_deprecated_char_limit() -> None:
    analysis = analyze_mcp_surface_cost(
        "prepare_session_distill",
        {"evidence_mode": "semantic"},
        _large_result(),
        duration_ms=10,
    )

    assert analysis["budget_exceeded"] is True
    assert "compact_distill_outline" in analysis["opportunity_kinds"]
    assert all("max_chars_per_observation" not in hint for hint in analysis["hints"])
