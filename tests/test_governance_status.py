"""Requirement-driven tests for auto-promoted memory governance."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.core.schemas import MemoryEntry, RelationFact
from harness_mem.read_api import search_memory
from harness_mem.search.backend import SQLiteSearchBackend, SearchFilters
from harness_mem.governance_status import (
    AUTO_CONFIRMED_STATUS,
    DEFERRED_STATUS,
    GOVERNANCE_STATUS_LIST,
    GOVERNANCE_STATUSES,
    PROVISIONAL_STATUS,
    READABLE_TRUTH_FILTER,
    USER_CONFIRMED_STATUS,
    is_readable_truth,
    resolve_promotion_status,
    statuses_for_list_filter,
    truth_weight,
    validate_status_transition,
)
from harness_mem.mcp import server
from harness_mem.mcp.tool_handlers import tool_list_candidates
from harness_mem.mcp.tool_specs import _SCHEMAS
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _tool_result(response: dict) -> dict:
    import json

    content = response["result"]["content"][0]["text"]
    return json.loads(content)


@pytest.fixture
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalMemoryBackend:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    yield backend
    asyncio.run(backend.close())


@pytest.mark.parametrize(
    ("from_status", "to_status", "allowed"),
    [
        ("pending", AUTO_CONFIRMED_STATUS, True),
        ("pending", PROVISIONAL_STATUS, True),
        ("pending", DEFERRED_STATUS, True),
        ("pending", "rejected", True),
        ("pending", USER_CONFIRMED_STATUS, True),
        (AUTO_CONFIRMED_STATUS, USER_CONFIRMED_STATUS, True),
        (PROVISIONAL_STATUS, USER_CONFIRMED_STATUS, True),
        (AUTO_CONFIRMED_STATUS, "superseded", True),
        ("rejected", "pending", False),
        ("superseded", USER_CONFIRMED_STATUS, False),
    ],
)
def test_status_transition_table(from_status: str, to_status: str, allowed: bool) -> None:
    assert validate_status_transition(from_status, to_status) is allowed


def test_resolve_promotion_status_low_risk_memory() -> None:
    status = resolve_promotion_status(
        action="auto_confirm",
        kind="memory_entry",
        is_high_risk=False,
        confidence=0.9,
    )
    assert status == AUTO_CONFIRMED_STATUS


def test_resolve_promotion_status_risky_rule() -> None:
    status = resolve_promotion_status(
        action="auto_confirm",
        kind="rule_candidate",
        is_high_risk=False,
        confidence=0.95,
    )
    assert status == PROVISIONAL_STATUS


def test_read_tier_visibility() -> None:
    assert is_readable_truth(AUTO_CONFIRMED_STATUS)
    assert is_readable_truth(USER_CONFIRMED_STATUS)
    assert not is_readable_truth(PROVISIONAL_STATUS)
    assert is_readable_truth(PROVISIONAL_STATUS, include_provisional=True)
    assert not is_readable_truth("pending")
    assert truth_weight(PROVISIONAL_STATUS) == 0.6
    assert truth_weight(AUTO_CONFIRMED_STATUS) == 1.0


def test_readable_truth_list_filter_includes_truth_layer() -> None:
    statuses = statuses_for_list_filter(READABLE_TRUTH_FILTER)
    assert AUTO_CONFIRMED_STATUS in statuses
    assert USER_CONFIRMED_STATUS in statuses
    assert PROVISIONAL_STATUS not in statuses


def test_schema_roundtrip_all_governance_statuses(backend: LocalMemoryBackend) -> None:
    store = backend.structured_store
    statuses = [
        "pending",
        DEFERRED_STATUS,
        "rejected",
        AUTO_CONFIRMED_STATUS,
        PROVISIONAL_STATUS,
        USER_CONFIRMED_STATUS,
        "superseded",
    ]
    saved_ids: list[str] = []
    for status in statuses:
        entry = MemoryEntry(
            project_name="gov-demo",
            category="decision",
            content=f"Governance status roundtrip for {status} with enough content.",
            source=f"obs:{status}",
            status=status,
        )
        saved_ids.append(asyncio.run(store.save_memory_entry(entry)))

    for entry_id, expected in zip(saved_ids, statuses, strict=True):
        loaded = asyncio.run(store.get_memory_entry(entry_id))
        assert loaded is not None
        assert loaded.status == expected


def test_auto_review_apply_promotes_to_auto_confirmed(backend: LocalMemoryBackend) -> None:
    entry = MemoryEntry(
        project_name="gov-demo",
        category="decision",
        content=(
            "Use the local SQLite derived index only as a rebuildable read model "
            "while canonical project truth remains in the structured store."
        ),
        source="observation:1",
        confidence=0.9,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    summary = asyncio.run(
        auto_review_candidates(backend, project_name="gov-demo", apply=True)
    )
    reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))

    assert summary.auto_confirmed == 1
    assert reloaded is not None
    assert reloaded.status == AUTO_CONFIRMED_STATUS


def test_auto_review_apply_borderline_promotes_to_provisional(
    backend: LocalMemoryBackend,
) -> None:
    entry = MemoryEntry(
        project_name="gov-demo",
        category="decision",
        content=(
            "Architecture note with borderline confidence that should stay visible "
            "but down-weighted until a human audits it in the inbox."
        ),
        source="observation:2",
        confidence=0.76,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    summary = asyncio.run(
        auto_review_candidates(backend, project_name="gov-demo", apply=True)
    )
    reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))

    assert summary.auto_provisional == 1
    assert reloaded is not None
    assert reloaded.status == PROVISIONAL_STATUS


def test_confirm_memory_entry_sets_user_confirmed(
    backend: LocalMemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    entry = MemoryEntry(
        project_name="gov-demo",
        category="decision",
        content="Pending decision awaiting explicit user confirmation in audit inbox.",
        source="observation:3",
        confidence=0.8,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))
    server.set_backend_override(backend)
    try:
        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "govern_memory",
                    "arguments": {
                        "action": "decide",
                        "arguments": {
                            "kind": "memory",
                            "decision": "confirm",
                            "candidate_id": entry.id,
                        },
                    },
                },
            }
        )
        payload = _tool_result(response)
        reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))
    finally:
        server.set_backend_override(None)

    assert payload["success"] is True
    assert payload["status"] == USER_CONFIRMED_STATUS
    assert reloaded is not None
    assert reloaded.status == USER_CONFIRMED_STATUS


def test_list_filter_excludes_provisional_by_default(
    backend: LocalMemoryBackend,
) -> None:
    store = backend.structured_store
    for status in (AUTO_CONFIRMED_STATUS, PROVISIONAL_STATUS, "pending"):
        asyncio.run(
            store.save_memory_entry(
                MemoryEntry(
                    project_name="gov-demo",
                    category="decision",
                    content=f"Filter visibility check for {status} with enough detail.",
                    source=f"obs:{status}",
                    status=status,
                )
            )
        )

    visible = asyncio.run(store.list_memory_entries("gov-demo", status=READABLE_TRUTH_FILTER))
    visible_statuses = {entry.status for entry in visible}
    assert AUTO_CONFIRMED_STATUS in visible_statuses
    assert PROVISIONAL_STATUS not in visible_statuses
    assert "pending" not in visible_statuses

    with_provisional = asyncio.run(
        store.list_memory_entries(
            "gov-demo", status=READABLE_TRUTH_FILTER, include_provisional=True
        )
    )
    assert any(entry.status == PROVISIONAL_STATUS for entry in with_provisional)


def test_invalid_status_transition_rejected(backend: LocalMemoryBackend) -> None:
    entry = MemoryEntry(
        project_name="gov-demo",
        category="decision",
        content="Rejected memory should not be promotable to auto_confirmed again.",
        source="obs:rej",
        status="rejected",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))
    updated = asyncio.run(
        backend.structured_store.update_memory_entry_status(
            entry.id, AUTO_CONFIRMED_STATUS
        )
    )
    assert updated is False


def test_relation_facts_list_includes_auto_confirmed_tier(
    backend: LocalMemoryBackend,
) -> None:
    store = backend.structured_store
    asyncio.run(
        store.save_relation_fact(
            RelationFact(
                project_name="gov-demo",
                source_entity="svc-a",
                target_entity="svc-b",
                relation_type="depends_on",
                evidence="auto confirmed relation tier visibility token",
                source="obs:auto",
                status=AUTO_CONFIRMED_STATUS,
            )
        )
    )
    asyncio.run(
        store.save_relation_fact(
            RelationFact(
                project_name="gov-demo",
                source_entity="svc-c",
                target_entity="svc-d",
                relation_type="depends_on",
                evidence="provisional relation tier visibility token",
                source="obs:prov",
                status=PROVISIONAL_STATUS,
            )
        )
    )
    visible = asyncio.run(store.list_relation_facts("gov-demo", status=READABLE_TRUTH_FILTER))
    statuses = {fact.status for fact in visible}
    assert AUTO_CONFIRMED_STATUS in statuses
    assert PROVISIONAL_STATUS not in statuses
    with_provisional = asyncio.run(
        store.list_relation_facts(
            "gov-demo", status=READABLE_TRUTH_FILTER, include_provisional=True
        )
    )
    assert any(fact.status == PROVISIONAL_STATUS for fact in with_provisional)


def test_search_memory_include_provisional_down_weights(
    backend: LocalMemoryBackend,
) -> None:
    store = backend.structured_store
    token = "provisionalsearchweighttoken"
    asyncio.run(
        store.save_memory_entry(
            MemoryEntry(
                project_name="gov-demo",
                category="decision",
                content=f"{token} auto confirmed full weight memory entry",
                source="obs:full",
                status=AUTO_CONFIRMED_STATUS,
            )
        )
    )
    asyncio.run(
        store.save_memory_entry(
            MemoryEntry(
                project_name="gov-demo",
                category="decision",
                content=f"{token} provisional down weighted memory entry",
                source="obs:prov",
                status=PROVISIONAL_STATUS,
            )
        )
    )
    default_entries, _ = asyncio.run(
        search_memory(
            backend,
            project_name="gov-demo",
            query=token,
            include_provisional=False,
            record_signals=False,
        )
    )
    assert len(default_entries) == 1
    assert default_entries[0].status == AUTO_CONFIRMED_STATUS

    provisional_entries, _ = asyncio.run(
        search_memory(
            backend,
            project_name="gov-demo",
            query=token,
            include_provisional=True,
            record_signals=False,
        )
    )
    assert {entry.status for entry in provisional_entries} == {
        AUTO_CONFIRMED_STATUS,
        PROVISIONAL_STATUS,
    }

    search_backend = SQLiteSearchBackend(backend)
    response = asyncio.run(
        search_backend.search(
            token,
            filters=SearchFilters(
                project_name="gov-demo",
                include_provisional=True,
            ),
            limit=10,
        )
    )
    weights = {
        result.metadata.get("governance_weight")
        for result in response.results
        if result.source_kind == "memory_entry"
    }
    assert 1.0 in weights
    assert 0.6 in weights


def test_relation_fact_roundtrip_and_confirm(backend: LocalMemoryBackend) -> None:
    fact = RelationFact(
        project_name="gov-demo",
        source_entity="service-a",
        target_entity="service-b",
        relation_type="depends_on",
        evidence="Import graph shows service-a imports service-b.",
        source="obs:rel",
        status="pending",
    )
    fact_id = asyncio.run(backend.structured_store.save_relation_fact(fact))
    confirmed = asyncio.run(
        backend.structured_store.update_relation_fact_status(
            fact_id, USER_CONFIRMED_STATUS
        )
    )
    reloaded = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
    assert confirmed is True
    assert reloaded is not None
    assert reloaded.status == USER_CONFIRMED_STATUS


@pytest.mark.parametrize("status", list(GOVERNANCE_STATUS_LIST))
def test_list_candidates_accepts_each_governance_status(
    backend: LocalMemoryBackend,
    status: str,
) -> None:
    project = "gov-list-demo"
    store = backend.structured_store
    if status in {"pending", "deferred", "rejected"}:
        asyncio.run(
            store.save_memory_entry(
                MemoryEntry(
                    project_name=project,
                    category="decision",
                    content=f"candidate layer {status}",
                    source="obs:candidate",
                    status=status,
                )
            )
        )
    elif status == "superseded":
        entry_id = asyncio.run(
            store.save_memory_entry(
                MemoryEntry(
                    project_name=project,
                    category="decision",
                    content="superseded truth entry",
                    source="obs:super",
                    status=USER_CONFIRMED_STATUS,
                )
            )
        )
        asyncio.run(
            store.update_memory_entry_status(entry_id, status)
        )
    else:
        asyncio.run(
            store.save_memory_entry(
                MemoryEntry(
                    project_name=project,
                    category="decision",
                    content=f"truth layer {status}",
                    source="obs:truth",
                    status=status,
                )
            )
        )

    server.set_backend_override(backend)
    try:
        result = tool_list_candidates(project_name=project, status=status, limit=10)
    finally:
        server.set_backend_override(None)

    assert result["success"] is True
    assert result["status"] == status
    assert result["total_count"] >= 1


def test_list_candidates_schema_matches_governance_enum() -> None:
    schema_enum = _SCHEMAS["list_candidates"]["input_schema"]["properties"]["status"]["enum"]
    assert schema_enum == list(GOVERNANCE_STATUS_LIST)
    assert set(schema_enum) == GOVERNANCE_STATUSES
