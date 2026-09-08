from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.event_log import iter_state_events
from harness_mem.mcp import read_wake_handlers, server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def _build():
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        return backend

    import asyncio

    backend = asyncio.run(_build())
    project_root = tmp_path / "demo"
    project_root.mkdir()
    (project_root / "SOURCE.md").write_text("# Test source\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    server.set_backend_override(backend)
    try:
        yield backend
    finally:
        server.set_backend_override(None)
        asyncio.run(backend.close())


def _replace_current_knowledge(
    backend: LocalMemoryBackend,
    project_name: str,
    statements: list[str],
) -> None:
    import asyncio

    project_root = backend.data_dir / project_name
    project_root.mkdir(exist_ok=True)
    source = project_root / "SOURCE.md"
    source.write_text("# Test source\n", encoding="utf-8")
    entries = [
        KnowledgeEntry(
            project_name=project_name,
            title="Project memory",
            statement=statement,
            module_path=["Test knowledge"],
            verified_at=datetime.now(timezone.utc),
        )
        for statement in statements
    ]
    candidate = KnowledgeCandidate(
        id=f"mcp-recall-seed-{project_name}",
        project_name=project_name,
        candidate_type="memory",
        statement="MCP recall fixture seed.",
    )
    decision = AssimilationDecision(
        id=f"mcp-recall-seed-mutation-{project_name}",
        project_name=project_name,
        candidate_id=candidate.id,
        disposition="add",
        canonical_truth_ids=[entry.id for entry in entries],
        reason="Test fixture.",
    )
    source_ref = ProjectKnowledgeSourceRef(
        label="SOURCE.md",
        target=source.resolve().as_uri(),
        kind="repository",
        digest="a" * 64,
    )
    asyncio.run(backend.structured_store.knowledge_store.save_candidate(candidate))
    asyncio.run(
        backend.structured_store.knowledge_store.apply_current_change(
            candidate_before=candidate,
            candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision,
            added_entries=entries,
            predecessor_entries=[],
            source_refs_by_entry={entry.id: [source_ref] for entry in entries},
        )
    )
    asyncio.run(
        backend.structured_store.knowledge_store.cleanup_candidate(candidate.id)
    )


def test_search_memory_returns_clean_canonical_prose_by_default(backend) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["Use SQLite for local-first memory."],
    )

    payload = server.tool_search_memory(
        query="SQLite local-first",
        project_name="demo",
    )

    assert payload["project_name"] == "demo"
    assert payload["query"] == "SQLite local-first"
    assert payload["status"] == "answered"
    assert payload["memories"] == [
        {
            "title": "Project memory",
            "statement": "Use SQLite for local-first memory.",
        }
    ]
    assert set(payload) == {"project_name", "query", "status", "memories"}
    assert "retrieval_id" not in payload
    assert "record_outcome_call" not in payload
    signals = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo",
            signal_type="search_hit",
            limit=20,
        )
    )
    assert len(signals) == 1
    assert signals[0].target_id
    assert signals[0].context["retrieval_id"]


def test_search_memory_and_wake_do_not_hide_current_entries_behind_default_count(
    backend,
) -> None:
    entries = [
        f"unboundedrecalltoken current decision {index}."
        for index in range(25)
    ]
    _replace_current_knowledge(backend, "demo", entries)

    search = server.tool_search_memory(
        query="unboundedrecalltoken",
        project_name="demo",
    )
    assert len(search["memories"]) == 25

    wake = server.tool_wake(
        project_name="demo",
        current_task="unboundedrecalltoken",
    )
    assert len(wake["long_term_memory"]) == 25


def test_search_memory_cannot_revive_legacy_rows(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["authorityfiltertoken current project decision."],
    )
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="authorityfiltertoken obsolete compatibility decision.",
                source="test",
                status="user_confirmed",
            )
        )
    )

    async def fail_legacy_read(*_args, **_kwargs):
        raise AssertionError("ordinary search must not inspect compatibility stores")

    monkeypatch.setattr(
        backend.structured_store,
        "search_memory_entries",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        backend.structured_store,
        "search_relation_facts",
        fail_legacy_read,
    )

    payload = server.tool_search_memory(
        query="authorityfiltertoken",
        project_name="demo",
    )

    assert payload["memories"] == [
        {
            "title": "Project memory",
            "statement": "authorityfiltertoken current project decision.",
        }
    ]
    assert "obsolete compatibility decision" not in str(payload)
    exclusions = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo",
            signal_type="retrieval_excluded",
            limit=20,
        )
    )
    assert exclusions == []


def test_search_all_cached_type_filter_uses_only_current_knowledge(backend) -> None:
    import asyncio

    for project_name in ("demo", "second"):
        _replace_current_knowledge(
            backend,
            project_name,
            [f"allauthoritytoken {project_name} current decision."],
        )
        asyncio.run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name=project_name,
                    category="decision",
                    content=f"allauthoritytoken {project_name} obsolete decision.",
                    source="test",
                    status="user_confirmed",
                )
            )
        )

    payload = server.tool_search_memory(
        query="allauthoritytoken",
        scope="all",
    )

    assert {
        (item["project_name"], item["statement"])
        for item in payload["memories"]
    } == {
        ("demo", "allauthoritytoken demo current decision."),
        ("second", "allauthoritytoken second current decision."),
    }
    assert "obsolete decision" not in str(payload)


def test_wake_uses_only_current_knowledge(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["wakeauthoritytoken current project decision."],
    )
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="wakeauthoritytoken obsolete compatibility decision.",
                source="test",
                status="user_confirmed",
            )
        )
    )

    current_search_calls = 0
    search_current = read_wake_handlers.search_current_knowledge

    async def count_current_search(*args, **kwargs):
        nonlocal current_search_calls
        current_search_calls += 1
        return await search_current(*args, **kwargs)

    monkeypatch.setattr(
        read_wake_handlers,
        "search_current_knowledge",
        count_current_search,
    )

    async def fail_legacy_read(*_args, **_kwargs):
        raise AssertionError("ordinary wake must not inspect compatibility stores")

    monkeypatch.setattr(
        backend.structured_store,
        "list_memory_entries",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        backend.structured_store,
        "get_memory_entry",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        backend.structured_store,
        "search_memory_entries",
        fail_legacy_read,
    )
    monkeypatch.setattr(
        backend.structured_store,
        "search_relation_facts",
        fail_legacy_read,
    )

    payload = server.tool_wake(
        project_name="demo",
        current_task="wakeauthoritytoken",
    )

    assert "current project decision" in str(payload)
    assert "obsolete compatibility decision" not in str(payload)
    assert current_search_calls == 1
    assert set(payload) == {
        "success",
        "project_name",
        "long_term_memory",
        "active_context",
        "maintenance_available",
    }


def test_wake_reports_degraded_storage_instead_of_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        read_wake_handlers,
        "_get_backend",
        lambda: SimpleNamespace(
            runtime_state="degraded_fallback",
            runtime_error="canonical store unavailable",
        ),
    )

    assert read_wake_handlers.tool_wake(project_name="demo") == {
        "success": False,
        "project_name": "demo",
        "message": "Project memory storage is not ready.",
        "action": "Run harness-mem doctor.",
    }


def test_file_context_reads_current_knowledge_not_legacy_memory(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["filecontextauthoritytoken harness_mem/file_context.py current guidance."],
    )
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content=(
                    "filecontextauthoritytoken harness_mem/file_context.py "
                    "obsolete compatibility guidance."
                ),
                source="test",
                status="user_confirmed",
            )
        )
    )

    async def fail_legacy_read(*_args, **_kwargs):
        raise AssertionError("file context must not inspect compatibility memory")

    for method_name in (
        "list_memory_entries",
        "get_memory_entry",
        "search_memory_entries",
        "list_confirmed_rules",
    ):
        monkeypatch.setattr(
            backend.structured_store,
            method_name,
            fail_legacy_read,
        )

    payload = server.tool_file_context(
        path="harness_mem/file_context.py",
        project_name="demo",
        project_root=str(backend.data_dir / "demo"),
    )

    assert payload["success"] is True, payload
    assert any(item["kind"] == "knowledge_entry" for item in payload["items"])
    assert "current guidance" in str(payload)
    assert "obsolete compatibility guidance" not in str(payload)


def test_search_all_returns_clean_current_knowledge_without_feedback_protocol(backend) -> None:
    import asyncio

    _replace_current_knowledge(backend, "demo", ["Shared SQLite guidance."])
    _replace_current_knowledge(backend, "second", ["Shared evidence guidance."])

    payload = server.tool_search_memory(query="Shared", scope="all")

    assert {row["project_name"] for row in payload["memories"]} == {
        "demo",
        "second",
    }
    assert set(payload) == {"project_name", "query", "status", "memories"}
    assert "retrieval_id" not in payload
    assert "record_outcome_calls" not in payload
    for project_name in ("demo", "second"):
        hits = asyncio.run(
            backend.structured_store.query_retrieval_signals(
                project_name,
                signal_type="search_hit",
                target_kind="knowledge_entry",
            )
        )
        assert len(hits) == 1


def test_search_memory_never_mixes_in_raw_observations(backend) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["canonicalretrievaltoken current memory."],
    )
    observation_id = asyncio.run(
        backend.verbatim_store.save(
            Observation(
                session_id="raw-session",
                client="codex",
                raw_content="canonicalretrievaltoken raw session evidence.",
                content_type="turn",
                metadata={"project_name": "demo"},
            )
        )
    )

    default_payload = server.tool_search_memory(
        query="canonicalretrievaltoken",
        project_name="demo",
    )
    raw_payload = server.tool_search_raw(
        pattern="canonicalretrievaltoken",
        project_name="demo",
    )

    assert default_payload["memories"] == [
        {
            "title": "Project memory",
            "statement": "canonicalretrievaltoken current memory.",
        }
    ]
    assert "raw session evidence" not in str(default_payload)
    assert [item["id"] for item in raw_payload["matches"]] == [observation_id]
    assert raw_payload["count"] == 1


def test_cross_project_search_keeps_only_the_needed_project_scope(backend) -> None:
    for project_name in ("demo", "other"):
        _replace_current_knowledge(
            backend,
            project_name,
            [f"sharedprojectiontoken {project_name} memory."],
        )

    payload = server.tool_search_memory(
        query="sharedprojectiontoken",
        scope="all",
    )

    assert payload["project_name"] is None
    assert {
        (item["project_name"], item["statement"])
        for item in payload["memories"]
    } == {
        ("demo", "sharedprojectiontoken demo memory."),
        ("other", "sharedprojectiontoken other memory."),
    }
    assert all(
        set(item) == {"project_name", "title", "statement"}
        for item in payload["memories"]
    )


def test_search_memory_records_content_free_abstention_signal(backend) -> None:
    import asyncio

    query = "evidence-that-does-not-exist-99331"
    payload = server.tool_search_memory(query=query, project_name="demo")
    signals = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo",
            signal_type="retrieval_abstained",
            limit=20,
        )
    )

    assert payload["memories"] == []
    assert payload["status"] == "empty"
    assert len(signals) == 1
    assert signals[0].context == {
        "surface": "search_memory",
        "reason": "no_evidence",
        "result_count": 0,
        "retrieval_id": signals[0].context["retrieval_id"],
    }
    assert query not in signals[0].target_id


def test_context_outcome_keeps_retrieval_correlation_without_prefilling_use(
    backend,
) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["Correlated retrieval feedback remains content free."],
    )
    search = server.tool_search_memory(
        query="correlated retrieval",
        project_name="demo",
        _include_diagnostics=True,
    )
    call = search["record_outcome_call"]

    assert "outcome" not in call["arguments"]
    recorded = server.tool_record_context_outcome(
        **call["arguments"],
        outcome="ignored",
    )
    replayed = server.tool_record_context_outcome(
        **call["arguments"],
        outcome="ignored",
    )
    outcomes = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo",
            signal_type="context_outcome",
            limit=20,
        )
    )

    assert recorded["retrieval_id"] == search["retrieval_id"]
    assert recorded["outcome"] == "ignored"
    assert replayed["signal_ids"] == recorded["signal_ids"]
    assert len(outcomes) == len(call["arguments"]["source_ids"])
    assert {signal.context["retrieval_id"] for signal in outcomes} == {
        search["retrieval_id"]
    }


def test_context_outcome_rejects_unmatched_sources_when_correlated(backend) -> None:
    import asyncio

    _replace_current_knowledge(
        backend,
        "demo",
        ["Current search feedback remains correlated."],
    )
    search = server.tool_search_memory(
        query="current search feedback",
        project_name="demo",
        _include_diagnostics=True,
    )
    arguments = {
        **search["record_outcome_call"]["arguments"],
        "source_ids": ["legacy-memory", "external-context"],
        "outcome": "used",
    }
    recorded = server.tool_record_context_outcome(**arguments)
    outcomes = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo", signal_type="context_outcome", limit=20
        )
    )

    assert recorded["success"] is False
    assert recorded["error"] == "retrieval_id did not resolve to surfaced context"
    assert outcomes == []


def test_mcp_review_writes_state_audit_events(backend) -> None:
    suggested = server.tool_govern_memory(
        action="suggest",
        arguments={
            "kind": "memory",
            "project_name": "demo",
            "category": "decision",
            "content": "State audit events are append-only.",
            "source": "test",
        },
    )
    reviewed = server.tool_govern_memory(
        action="decide",
        arguments={
            "kind": "knowledge",
            "decision": "reject",
            "project_name": "demo",
            "candidate_id": suggested["entry_id"],
            "disposition": "reject",
            "reason": "This audit fixture is not durable project knowledge.",
        },
    )

    events = list(iter_state_events(backend.data_dir, project_name="demo"))

    assert suggested["state_event_id"]
    assert reviewed["state_event_id"]
    assert [event["type"] for event in events] == [
        "candidate_created",
        "candidate_reviewed",
    ]
    assert [event["target_id"] for event in events] == [
        suggested["entry_id"],
        suggested["entry_id"],
    ]


def test_mcp_search_memory_diagnostics_never_surface_legacy_rows(backend) -> None:
    import asyncio

    past = datetime.now(timezone.utc) - timedelta(days=1)
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpdeeprecalltoken historical memory",
                source="test",
                status="user_confirmed",
                valid_to=past,
            )
        )
    )

    default_payload = server.tool_search_memory(
        query="mcpdeeprecalltoken",
        project_name="demo",
    )
    diagnostic_payload = server.tool_search_memory(
        query="mcpdeeprecalltoken",
        project_name="demo",
        _include_diagnostics=True,
    )

    assert default_payload["memories"] == []
    assert diagnostic_payload["memories"] == []
    assert "historical memory" not in str(diagnostic_payload)
    exclusions = asyncio.run(
        backend.structured_store.query_retrieval_signals(
            "demo",
            signal_type="retrieval_excluded",
            limit=20,
        )
    )
    assert exclusions == []


def test_mcp_does_not_supersede_legacy_memory_rows(backend) -> None:
    import asyncio

    old_id = asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpsupersedetoken old decision",
                source="test",
                status="user_confirmed",
            )
        )
    )
    new_id = asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpsupersedetoken new decision",
                source="test",
                status="user_confirmed",
            )
        )
    )

    suggested = server.tool_govern_memory(
        action="supersede",
        arguments={
            "project_name": "demo",
            "target_type": "memory_entry",
            "target_id": old_id,
            "replacement_type": "memory_entry",
            "replacement_id": new_id,
            "reason": "New decision replaces old decision.",
            "evidence": "test evidence",
        },
    )
    old_entry = asyncio.run(backend.structured_store.get_memory_entry(old_id))
    new_entry = asyncio.run(backend.structured_store.get_memory_entry(new_id))

    assert suggested["success"] is False
    assert old_entry is not None
    assert old_entry.valid_to is None
    assert old_entry.superseded_by == []
    assert new_entry is not None
    assert new_entry.supersedes == []
