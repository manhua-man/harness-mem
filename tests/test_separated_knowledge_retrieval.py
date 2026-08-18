"""Default retrieval is clean once a project has separated knowledge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
                statement="Data ingestion must preserve traceable original evidence before normalization.",
                module_path=["data ingestion"],
                verified_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
            ),
            KnowledgeEntry(
                project_name="demo",
                title="Preserve original evidence first",
                statement="Data ingestion must preserve traceable original evidence before normalization.",
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
            store.apply_truth_mutation(
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
                "statement": "Data ingestion must preserve traceable original evidence before normalization.",
            }
        ]

        monkeypatch.setattr(read_search_handlers, "_get_backend", lambda: backend)
        payload = read_search_handlers.tool_search_memory(
            query="evidence",
            project_name="demo",
        )
        assert payload == {
            "project_name": "demo",
            "query": "evidence",
            "status": "answered",
            "memories": [
                {
                    "title": "Preserve original evidence first",
                    "statement": "Data ingestion must preserve traceable original evidence before normalization.",
                }
            ],
        }
    finally:
        _run(backend.close())
