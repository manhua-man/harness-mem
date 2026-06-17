"""Loop harness scenario 11 — context outcome signals influence opt-in search.

Business question:
When an agent rates returned context as used / ignored / misleading, does that
signal stay outside truth while becoming visible as an explainable ranking hint
on the next opt-in search?

Loop:

search result source_id
  -> record_context_outcome writes RetrievalSignal(context_outcome)
  -> SearchBackend reads recent signals when weak_link_signals=True
  -> MCP search returns per-source ranking_explanation metadata
"""

from __future__ import annotations

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.mcp.server import (
    set_backend_override,
    tool_record_context_outcome,
    tool_search_memory,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics


pytestmark = pytest.mark.loop_harness


def test_context_outcome_loop_is_explainable_and_truth_safe(
    backend: LocalMemoryBackend,
) -> None:
    project_name = "loop-context-outcome"
    entry_used = MemoryEntry(
        id="context-loop-used",
        project_name=project_name,
        category="decision",
        content="Context outcome loop should reuse SQLite FTS fallback metadata.",
        source="manual",
        confidence=0.9,
    )
    entry_misleading = MemoryEntry(
        id="context-loop-misleading",
        project_name=project_name,
        category="decision",
        content="Context outcome loop should ignore obsolete SQLite FTS fallback metadata.",
        source="manual",
        confidence=0.9,
    )
    run(backend.structured_store.save_memory_entry(entry_used))
    run(backend.structured_store.save_memory_entry(entry_misleading))
    before_count = len(
        run(backend.structured_store.list_memory_entries(project_name, limit=20))
    )

    run(
        LocalProjectProfileStore(backend.data_dir).save(
            ProjectProfile(project_name=project_name, weak_link_signals=True)
        )
    )

    set_backend_override(backend)
    try:
        first_search = tool_search_memory(
            project_name=project_name,
            query="Context outcome loop SQLite FTS fallback metadata",
            mode="fts",
        )
        returned_ids = {item["id"] for item in first_search["memory_entries"]}
        assert {entry_used.id, entry_misleading.id}.issubset(returned_ids)

        used = tool_record_context_outcome(
            project_name=project_name,
            surface="search_memory",
            source_ids=[entry_used.id],
            outcome="used",
            reason="helped answer the fallback metadata question",
        )
        misleading = tool_record_context_outcome(
            project_name=project_name,
            surface="search_memory",
            source_ids=[entry_misleading.id],
            outcome="misleading",
            reason="obsolete instruction for the task",
        )
        assert used["truth_mutated"] is False
        assert misleading["truth_mutated"] is False

        second_search = tool_search_memory(
            project_name=project_name,
            query="Context outcome loop SQLite FTS fallback metadata",
            mode="fts",
        )
    finally:
        set_backend_override(None)

    after_count = len(
        run(backend.structured_store.list_memory_entries(project_name, limit=20))
    )
    signals = run(
        backend.structured_store.query_retrieval_signals(
            project_name,
            signal_type="context_outcome",
            target_kind="context_source",
        )
    )
    entries = {item["id"]: item for item in second_search["memory_entries"]}

    used_score = entries[entry_used.id]["context_outcome_score"]
    misleading_score = entries[entry_misleading.id]["context_outcome_score"]
    explained_count = sum(
        1
        for item in (entries[entry_used.id], entries[entry_misleading.id])
        if any(
            explanation["kind"] == "context_outcome"
            for explanation in item["ranking_explanation"]
        )
    )
    truth_mutation_count = after_count - before_count

    LoopMetrics(
        name="context_outcome_loop",
        values={
            "context_outcome_signals": float(len(signals)),
            "used_score_positive": 1.0 if used_score > 0 else 0.0,
            "misleading_score_negative": 1.0 if misleading_score < 0 else 0.0,
            "explained_result_count": float(explained_count),
            "truth_mutation_count": float(truth_mutation_count),
        },
    ).report()

    assert len(signals) == 2
    assert used_score > 0
    assert misleading_score < 0
    assert explained_count == 2
    assert truth_mutation_count == 0
