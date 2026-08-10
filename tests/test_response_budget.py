from __future__ import annotations

from harness_mem.mcp.response_budget import (
    attach_response_budget_receipt,
    refresh_response_budget_receipt,
    serialize_mcp_result,
    serialized_result_tokens,
)
from harness_mem.runtime_cost import analyze_mcp_surface_cost


def test_receipt_measures_itself_in_the_exact_executor_serialization() -> None:
    payload = {"success": True, "semantic_evidence": {"content": "evidence"}}

    attach_response_budget_receipt(
        payload,
        requested_tokens=3000,
        evidence_tokens=2,
    )

    tokens, tokenizer, chars = serialized_result_tokens(payload)
    receipt = payload["response_budget"]
    assert receipt["serialized_tokens"] == tokens
    assert receipt["serialized_chars"] == chars == len(serialize_mcp_result(payload))
    assert receipt["tokenizer"] == tokenizer
    assert receipt["outcome"] == "within_target"
    assert receipt["hard_truncation_applied"] is False


def test_soft_target_expands_with_a_reason_instead_of_clipping_json() -> None:
    marker = "late-exchange-proof"
    payload = {"success": True, "content": ("large response " * 1000) + marker}

    attach_response_budget_receipt(
        payload,
        requested_tokens=256,
        outcome_hint="expanded_for_complete_manifest",
        reason_hint="all exchange indexes must remain represented",
    )

    rendered = serialize_mcp_result(payload)
    receipt = payload["response_budget"]
    assert marker in rendered
    assert receipt["serialized_tokens"] > receipt["requested_target_tokens"]
    assert receipt["outcome"] == "expanded_for_complete_manifest"
    assert receipt["reason"] == "all exchange indexes must remain represented"
    assert receipt["hard_truncation_applied"] is False


def test_runtime_cost_counts_the_same_text_the_agent_receives() -> None:
    payload = {"success": True, "nested": {"cjk": "完整响应", "items": [1, 2]}}
    expected_tokens, _tokenizer, expected_chars = serialized_result_tokens(payload)

    analysis = analyze_mcp_surface_cost(
        "prepare_session_distill",
        {"budget_tokens": 3000},
        payload,
        duration_ms=1,
    )

    assert analysis["output_tokens"] == expected_tokens
    assert analysis["output_chars"] == expected_chars


def test_executor_level_fields_are_included_after_receipt_refresh() -> None:
    payload = {"success": True, "semantic_evidence": {"content": "small"}}
    attach_response_budget_receipt(
        payload,
        requested_tokens=256,
        evidence_tokens=1,
    )
    before = payload["response_budget"]["serialized_tokens"]

    payload["surface_enforcement"] = {"explanation": "x" * 4000}
    refresh_response_budget_receipt(payload)

    tokens, _tokenizer, _chars = serialized_result_tokens(payload)
    assert payload["response_budget"]["serialized_tokens"] == tokens
    assert tokens > before
    assert payload["response_budget"]["outcome"] == (
        "expanded_for_required_metadata"
    )
