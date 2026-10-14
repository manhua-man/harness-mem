"""Default retrieval is clean once a project has separated knowledge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.mcp import read_search_handlers
from harness_mem.mcp.read_projection import project_memory_entries
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("query", [".env", "【.env】", "`.env`", "【 锁 】", "锁"])
def test_exact_keywords_preserve_technical_punctuation_and_single_characters(query) -> None:
    entries = [
        KnowledgeEntry(project_name="fixture", title="Process environment", module_path=["Environment"],
                       statement="Use env to inspect environment variables."),
        KnowledgeEntry(project_name="fixture", title="Environment file", module_path=["Environment"],
                       statement="Load settings from the .env file."),
        KnowledgeEntry(project_name="fixture", title="锁", module_path=["Concurrency"],
                       statement="临界区使用互斥锁保护。"),
    ]
    backend = SimpleNamespace(structured_store=SimpleNamespace(
        knowledge_store=SimpleNamespace(list_entries=AsyncMock(return_value=entries)),
    ))
    found = _run(search_current_knowledge(backend, project_name="fixture", query=query))
    assert found == [entries[2] if "锁" in query else entries[1]]


def test_separated_knowledge_search_is_current_only_and_clean(
    tmp_path, monkeypatch
) -> None:
    project_root = tmp_path / "demo"
    project_root.mkdir()
    source = project_root / "README.md"
    source.write_text("# Demo\n\nPreserve original evidence.\n", encoding="utf-8")
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        source_ref = ProjectKnowledgeSourceRef(
            label="README.md",
            target=source.resolve().as_uri(),
            kind="repository",
            digest="a" * 64,
        )
        entries = [
            KnowledgeEntry(
                project_name="demo",
                title="Preserve original evidence first",
                statement=(
                    "Data ingestion must preserve traceable original evidence before "
                    "normalization. Markdown may be generated for reading."
                ),
                module_path=["data ingestion"],
                verified_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
            ),
            KnowledgeEntry(
                project_name="demo",
                title="Preserve original evidence first",
                statement=(
                    "Data ingestion must preserve traceable original evidence before "
                    "normalization. Markdown may be generated for reading."
                ),
                module_path=["data ingestion"],
                verified_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
            ),
        ]
        candidate = KnowledgeCandidate(
            id="retrieval-seed",
            project_name="demo",
            candidate_type="memory",
            statement="Retrieval seed.",
        )
        decision = AssimilationDecision(
            id="retrieval-seed-mutation",
            project_name="demo",
            candidate_id=candidate.id,
            disposition="add",
            canonical_truth_ids=[entry.id for entry in entries],
            reason="Test fixture.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.apply_current_change(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=decision,
                added_entries=entries,
                predecessor_entries=[],
                source_refs_by_entry={entry.id: [source_ref] for entry in entries},
            )
        )
        with pytest.raises(ValidationError):
            KnowledgeEntry(
                id="historical-evidence",
                project_name="demo",
                title="Old evidence rule",
                statement="An obsolete previous rule.",
                module_path=["data ingestion"],
                validity="historical",
            )

        entries = _run(
            search_current_knowledge(
                backend,
                project_name="demo",
                query="evidence",
                limit=10,
                project_root=project_root,
            )
        )
        assert len(entries) == 1
        assert (
            _run(
                list_current_knowledge(
                    backend, project_name="demo", limit=10, project_root=project_root
                )
            )
            == entries
        )
        assert project_memory_entries(entries) == [
            {
                "title": "Preserve original evidence first",
                "statement": (
                    "Data ingestion must preserve traceable original evidence before "
                    "normalization. Markdown may be generated for reading."
                ),
            }
        ]
        assert (
            _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="unrelated-token",
                    limit=10,
                    project_root=project_root,
                )
            )
            == []
        )
        assert (
            _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="mark prune parser choices",
                    limit=10,
                    project_root=project_root,
                )
            )
            == []
        )
        assert (
            _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="markdown",
                    limit=10,
                    project_root=project_root,
                )
            )
            == entries
        )
        assert (
            _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="",
                    limit=10,
                    project_root=project_root,
                )
            )
            == entries
        )

        monkeypatch.setattr(read_search_handlers, "_get_backend", lambda: backend)
        payload = read_search_handlers.tool_search_memory(
            query="evidence",
            project_name="demo",
            scope="project",
        )
        assert payload["project_name"] == "demo"
        assert payload["query"] == "evidence"
        assert payload["status"] == "answered"
        assert payload["memories"] == [
            {
                "title": "Preserve original evidence first",
                "statement": (
                    "Data ingestion must preserve traceable original evidence before "
                    "normalization. Markdown may be generated for reading."
                ),
            }
        ]
        assert set(payload) == {"project_name", "query", "status", "memories"}
        assert "retrieval_id" not in payload
        assert "record_outcome_call" not in payload

        diagnostics = read_search_handlers.tool_search_memory(
            query="evidence",
            project_name="demo",
            scope="project",
            _include_diagnostics=True,
        )
        assert diagnostics["memory_count"] == 1
        assert diagnostics["context_plan"]["source_ids"] == [entries[0].id]
        assert diagnostics["answer_ready_context"]["truth"] == [
            {
                "source_id": entries[0].id,
                "reason": "current project knowledge matched the query",
                "summary": (
                    "Preserve original evidence first: Data ingestion must preserve "
                    "traceable original evidence before normalization. Markdown may be "
                    "generated for reading."
                ),
            }
        ]
        assert diagnostics["record_outcome_call"] is not None

        autopilot = read_search_handlers.tool_autopilot_search_tick(
            event_name="context",
            project_name="demo",
            current_task=(
                "Need the current project convention for preserving source evidence; "
                "not sure about the existing rule."
            ),
            changed_files=["README.md"],
        )
        assert autopilot["search_executed"] is True
        assert len(autopilot["context_injection"]["memories"]) == 1
        assert autopilot["context_injection"]["source_ids"] == [entries[0].id]
        assert autopilot["context_injection"]["memories"]
    finally:
        _run(backend.close())


@pytest.mark.parametrize(
    "query, expected",
    [
        ("后台整理", True),
        ("开", True),
        ("【后台整理】", True),
        ("`后台整理`", True),
        ("后台整理怎么开启？", True),
        ("请问之前如何开启后台整理", True),
        ("整理后台如何开启", True),
        ("以前怎么开启后台整理？", True),
        ("怎么开启飞船引擎？", False),
        ("后台音乐怎么播放？", False),
        ("自动删除怎么开启？", False),
        ("请问这个问题怎么处理？", False),
    ],
)
def test_chinese_questions_retrieve_only_matching_current_knowledge(
    tmp_path, monkeypatch, query, expected
) -> None:
    root = tmp_path / "fictional-project"
    root.mkdir()
    source = root / "README.md"
    source.write_text("Fictional retrieval fixture.\n", encoding="utf-8")
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        entry = KnowledgeEntry(
            project_name="fictional-project",
            title="开启后台整理",
            statement="后台整理默认关闭，只有明确开启后才会自动整理会话。",
            module_path=["后台使用"],
        )
        candidate = KnowledgeCandidate(
            project_name=entry.project_name,
            candidate_type="memory",
            statement=entry.statement,
        )
        decision = AssimilationDecision(
            project_name=entry.project_name,
            candidate_id=candidate.id,
            disposition="add",
            canonical_truth_ids=[entry.id],
            reason="Isolated Chinese retrieval fixture.",
        )
        _run(store.save_candidate(candidate))
        _run(store.apply_current_change(
            candidate_before=candidate,
            candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision,
            added_entries=[entry],
            predecessor_entries=[],
            source_refs_by_entry={entry.id: [ProjectKnowledgeSourceRef(
                label="README.md", target=source.as_uri(),
                kind="repository", digest="d" * 64,
            )]},
        ))
        # Reopen the persisted store and use the ordinary public read path.
        _run(backend.close())
        backend = LocalMemoryBackend(tmp_path / "data")
        _run(backend.init())
        monkeypatch.setattr(read_search_handlers, "_get_backend", lambda: backend)
        payload = read_search_handlers.tool_search_memory(
            query=query, project_name=entry.project_name,
        )
        assert payload["status"] == ("answered" if expected else "empty")
        assert payload["memories"] == (
            [{"title": entry.title, "statement": entry.statement, "project_name": entry.project_name}]
            if expected else []
        )
        assert _run(search_current_knowledge(
            backend, project_name="another-project", query=query,
        )) == []
        assert len(_run(list_current_knowledge(
            backend, project_name=entry.project_name,
        ))) == 1
    finally:
        _run(backend.close())
