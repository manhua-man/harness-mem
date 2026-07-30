from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from harness_mem.mcp.serializers import (
    _serialize_memory_entry_candidate,
    _serialize_relation_fact_candidate,
    _serialize_rule_candidate,
    _serialize_supersede_candidate,
)
from harness_mem.mcp.tool_specs import INTERNAL_MCP_TOOL_NAMES


def _candidate(**overrides):
    values = {
        "id": "candidate-1",
        "project_name": "demo",
        "status": "pending",
        "pattern": "Use one public governance surface",
        "trigger": "When reviewing a candidate",
        "examples": [],
        "confidence": 0.9,
        "session_id": "session-1",
        "created_at": None,
        "category": "decision",
        "memory_type": "semantic",
        "content": "Use govern_memory",
        "source": "session-1",
        "tags": [],
        "updated_at": None,
        "provenance": {},
        "source_entity": "Agent",
        "target_entity": "Memory",
        "relation_type": "uses",
        "evidence": "The public contract requires it",
        "target_type": "memory_entry",
        "target_id": "old-memory",
        "replacement_type": "memory_entry",
        "replacement_id": "new-memory",
        "reason": "Current evidence supersedes it",
        "reviewed_at": None,
        "reviewer_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("serializer", "expected_action", "expected_kind"),
    [
        (_serialize_rule_candidate, "decide", "rule"),
        (_serialize_memory_entry_candidate, "decide", "memory"),
        (_serialize_relation_fact_candidate, "decide", "relation"),
        (_serialize_supersede_candidate, "supersede", None),
    ],
)
def test_candidate_review_actions_use_the_public_governance_tool(
    serializer,
    expected_action: str,
    expected_kind: str | None,
) -> None:
    payload = serializer(_candidate())
    serialized = json.dumps(payload, sort_keys=True)

    for internal_name in INTERNAL_MCP_TOOL_NAMES:
        assert internal_name not in serialized
    assert set(payload["review_actions"]) == {"confirm", "reject"}
    for decision, action_hint in payload["review_actions"].items():
        assert action_hint["tool"] == "govern_memory"
        assert action_hint["arguments"]["action"] == expected_action
        nested = action_hint["arguments"]["arguments"]
        assert nested["candidate_id"] == payload["id"]
        assert nested["decision"] == decision
        if expected_kind is not None:
            assert nested["kind"] == expected_kind
