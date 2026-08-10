"""Honest accounting for the complete serialized MCP response.

Response budgets are advisory targets.  They never authorize clipping JSON or
dropping evidence; callers receive an explicit receipt whenever complete
coverage, requested detail, or required protocol metadata exceeds the target.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, MutableMapping


RESPONSE_BUDGET_CONTRACT_VERSION = "serialized-response-budget-v1"


def serialize_mcp_result(result: Any) -> str:
    """Serialize exactly as the MCP executor sends ``content.text``."""

    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def count_response_tokens(value: str) -> tuple[int, str]:
    """Return the repository tokenizer count and its observable implementation."""

    from harness_mem.commands import token_estimator

    return token_estimator.count_tokens(value), token_estimator.tokenizer_kind


def serialized_result_tokens(result: Any) -> tuple[int, str, int]:
    """Measure the exact serialized MCP result body."""

    rendered = serialize_mcp_result(result)
    tokens, tokenizer = count_response_tokens(rendered)
    return tokens, tokenizer, len(rendered)


def attach_response_budget_receipt(
    result: MutableMapping[str, Any],
    *,
    requested_tokens: int,
    evidence_tokens: int = 0,
    outcome_hint: str | None = None,
    reason_hint: str | None = None,
) -> MutableMapping[str, Any]:
    """Attach a fixed-point receipt for the complete serialized result.

    The receipt is part of the measured response, so its own token cost is
    included.  Updating the integer fields converges once their digit widths
    stop changing; the bounded loop is a safety guard, not a truncation path.
    """

    target = max(256, int(requested_tokens or 3000))
    evidence = max(0, int(evidence_tokens or 0))
    receipt: dict[str, Any] = {
        "contract_version": RESPONSE_BUDGET_CONTRACT_VERSION,
        "scope": "mcp_content_text",
        "requested_target_tokens": target,
        "evidence_tokens": evidence,
        "protocol_tokens": 0,
        "protocol_tokens_basis": "serialized_minus_evidence_estimate",
        "serialized_tokens": 0,
        "serialized_chars": 0,
        "tokenizer": None,
        "outcome": "within_target",
        "reason": None,
        "hard_truncation_applied": False,
    }
    result["response_budget"] = receipt

    for _ in range(8):
        serialized_tokens, tokenizer, serialized_chars = serialized_result_tokens(
            result
        )
        exceeds_target = serialized_tokens > target
        outcome = (
            outcome_hint
            if exceeds_target and outcome_hint
            else "expanded_for_required_metadata"
            if exceeds_target
            else "within_target"
        )
        reason = (
            reason_hint
            if exceeds_target and reason_hint
            else "the complete serialized response exceeds the advisory target"
            if exceeds_target
            else None
        )
        updated = {
            **receipt,
            "protocol_tokens": max(0, serialized_tokens - evidence),
            "serialized_tokens": serialized_tokens,
            "serialized_chars": serialized_chars,
            "tokenizer": tokenizer,
            "outcome": outcome,
            "reason": reason,
        }
        if updated == receipt:
            break
        receipt.clear()
        receipt.update(updated)

    return result


def distill_response_budget_hints(
    result: Mapping[str, Any],
) -> tuple[int, str | None, str | None]:
    """Derive evidence cost and any legitimate expansion reason."""

    evidence = result.get("semantic_evidence")
    evidence_payload = dict(evidence) if isinstance(evidence, Mapping) else {}
    evidence_tokens = int(evidence_payload.get("output_tokens") or 0)

    if any(
        key in result
        for key in (
            "raw_drilldown_chunks",
            "semantic_drilldown_exchanges",
        )
    ):
        return (
            evidence_tokens,
            "expanded_for_explicit_drilldown",
            "explicit semantic or raw drilldown was requested",
        )
    if str(result.get("detail_level") or "") == "full":
        return (
            evidence_tokens,
            "expanded_for_full_detail",
            "full semantic detail was explicitly requested",
        )
    if str(result.get("evidence_mode") or "") == "raw":
        return (
            evidence_tokens,
            "expanded_for_full_detail",
            "raw compatibility evidence was requested",
        )
    if evidence_payload.get("budget_state") == "full_fallback":
        return (
            evidence_tokens,
            "expanded_for_required_metadata",
            str(evidence_payload.get("budget_reason") or "")
            or "parser rendering has no exchange boundaries",
        )
    if evidence_payload.get("budget_state") == "expanded_for_manifest":
        return (
            evidence_tokens,
            "expanded_for_complete_manifest",
            str(evidence_payload.get("budget_reason") or "")
            or "the minimum complete indexed manifest exceeds the advisory target",
        )
    if result.get("evidence_mode_fallback_reason"):
        return (
            evidence_tokens,
            "expanded_for_required_metadata",
            "the requested compact semantic path fell back to compatibility evidence",
        )
    return evidence_tokens, None, None


def refresh_response_budget_receipt(
    result: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Re-measure a receipt after executor-level fields have been appended."""

    existing = result.get("response_budget")
    if not isinstance(existing, Mapping):
        return result
    outcome = str(existing.get("outcome") or "")
    return attach_response_budget_receipt(
        result,
        requested_tokens=int(existing.get("requested_target_tokens") or 3000),
        evidence_tokens=int(existing.get("evidence_tokens") or 0),
        outcome_hint=outcome if outcome and outcome != "within_target" else None,
        reason_hint=(
            str(existing.get("reason")) if existing.get("reason") else None
        ),
    )


__all__ = [
    "RESPONSE_BUDGET_CONTRACT_VERSION",
    "attach_response_budget_receipt",
    "count_response_tokens",
    "distill_response_budget_hints",
    "refresh_response_budget_receipt",
    "serialize_mcp_result",
    "serialized_result_tokens",
]
