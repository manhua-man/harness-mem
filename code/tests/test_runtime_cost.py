from __future__ import annotations

from harness_mem.mcp.response_budget import serialized_result_tokens
from harness_mem.runtime_cost import analyze_mcp_surface_cost


def _large_result() -> dict:
    return {"output": "token " * 6000}


def test_budget_exceeded_is_not_reported_as_actual_truncation() -> None:
    analysis = analyze_mcp_surface_cost(
        "get_project_status",
        {},
        _large_result(),
        duration_ms=10,
        surface_budgets={"status": 1200},
    )

    assert analysis["budget_exceeded"] is True
    assert analysis["truncation"]["truncated_by"] is None
    assert analysis["argument_shape"] == {}
    assert analysis["opportunity_kinds"] == []


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


def test_output_equal_to_surface_target_is_within_budget() -> None:
    result = {"success": True, "value": "exact accounting"}
    exact_tokens, _tokenizer, _chars = serialized_result_tokens(result)

    analysis = analyze_mcp_surface_cost(
        "prepare_session_distill",
        {},
        result,
        duration_ms=1,
        surface_budgets={"distill": exact_tokens},
    )

    assert analysis["output_tokens"] == exact_tokens
    assert analysis["high_output"] is False
    assert analysis["budget_exceeded"] is False
