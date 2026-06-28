"""Requirement-driven tests for auto-promoted memory governance."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.core.schemas import MemoryEntry, RelationFact, RuleCandidate
from harness_mem.governance_status import (
    AUTO_CONFIRMED_STATUS,
    DEFERRED_STATUS,
    PROVISIONAL_STATUS,
    USER_CONFIRMED_STATUS,
    is_readable_truth,
    resolve_promotion_status,
    statuses_for_list_filter,
    truth_weight,
    validate_status_transition,
)
from harness_mem.mcp import server
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
    assert is_readable_truth("accepted")
    assert is_readable_truth(AUTO_CONFIRMED_STATUS)
    assert is_readable_truth(USER_CONFIRMED_STATUS)
    assert not is_readable_truth(PROVISIONAL_STATUS)
    assert is_readable_truth(PROVISIONAL_STATUS, include_provisional=True)
    assert not is_readable_truth("pending")
    assert truth_weight(PROVISIONAL_STATUS) == 0.6
    assert truth_weight(AUTO_CONFIRMED_STATUS) == 1.0


def test_legacy_accepted_list_filter_includes_promoted_statuses() -> None:
    statuses = statuses_for_list_filter("accepted")
    assert AUTO_CONFIRMED_STATUS in statuses
    assert USER_CONFIRMED_STATUS in statuses
    assert "accepted" in statuses
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
        "accepted",
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
                    "name": "confirm_memory_entry",
                    "arguments": {"entry_id": entry.id},
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

    visible = asyncio.run(store.list_memory_entries("gov-demo", status="accepted"))
    visible_statuses = {entry.status for entry in visible}
    assert AUTO_CONFIRMED_STATUS in visible_statuses
    assert PROVISIONAL_STATUS not in visible_statuses
    assert "pending" not in visible_statuses

    with_provisional = asyncio.run(
        store.list_memory_entries(
            "gov-demo", status="accepted", include_provisional=True
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