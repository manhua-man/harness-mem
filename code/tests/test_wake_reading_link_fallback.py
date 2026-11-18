"""Wake-only budget recovery with fake lookup and side-effect owners."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from harness_mem.commands import wake
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.mcp.read_projection import reading_tokens, select_memory_page


@pytest.fixture
def selection(monkeypatch):
    entries = [KnowledgeEntry(id="memory", project_name="demo", module_path=["facts"],
        title="Complete knowledge", statement="A complete reusable source statement.")]
    backend = object()
    state = SimpleNamespace(entries=entries, searches=[], effects=[])

    async def search(actual, **kwargs):
        assert actual is backend
        state.searches.append(kwargs)
        return state.entries

    async def effects(actual, page):
        assert actual is backend
        state.effects.append(page)

    monkeypatch.setattr(wake, "search_current_knowledge", search)
    monkeypatch.setattr(wake, "_apply_surface_side_effects", effects)
    return backend, state


def inject(selection, **kwargs):
    return asyncio.run(wake.build_wake_injection(selection[0], "demo", **kwargs))


@pytest.mark.parametrize("query", [("complete unabridged task " * 500).strip(),
    "继续当前完整任务🧠保留原始要求。" * 300], ids=["long_ascii", "long_unicode"])
def test_long_query_keeps_full_search_and_returns_only_bounded_honest_notice(selection, query):
    state = selection[1]
    state.entries[0].statement = "Complete memory body must never be clipped. " * 1000
    receipt = {}
    output = inject(selection, current_task=query, budget_tokens=200, selection_receipt=receipt)
    assert state.searches == [{"query": query, "expand_long_query": True}]
    assert reading_tokens(output) <= 200
    assert "1 keyword candidates found" in output
    assert "no previews fit" in output and "focused task" in output
    assert "Continue reading:" not in output and "cursor" not in output and query not in output
    assert state.entries[0].title not in output and state.entries[0].statement not in output
    assert receipt == {"query_present": True, "matched_count": 1, "returned_count": 0,
                       "candidate_count": 0, "index_only": True}
    assert not state.effects


def test_short_query_exposes_incomplete_candidate_and_exact_full_read(selection):
    receipt = {}
    output = inject(selection, current_task="short task", budget_tokens=500, selection_receipt=receipt)
    assert "## Complete knowledge (demo)" in output
    assert "Incomplete preview:" in output and "not verified relevant" in output
    assert selection[1].entries[0].statement not in output
    cursor = output.split("read_cursor: ", 1)[1].splitlines()[0]
    page, _, index = select_memory_page(
        selection[1].entries, query="short task", project_name=None, scope="all",
        budget_tokens=1, render=lambda *args: "unused", cursor=cursor, detail="full",
    )
    assert page == selection[1].entries and index is False
    assert receipt == {"query_present": True, "matched_count": 1, "returned_count": 0,
                       "candidate_count": 1, "index_only": True}
    assert not selection[1].effects


def test_long_memory_candidate_has_strict_full_read_and_no_surface_effect(selection):
    selection[1].entries[0].statement = "A complete long memory. " * 2000
    receipt = {}
    output = inject(selection, current_task="short task", budget_tokens=300, selection_receipt=receipt)
    assert "read_cursor: " in output and 'query: "short task"' in output
    assert "detail=full" in output and "Continue reading:" not in output
    cursor = output.split("read_cursor: ", 1)[1].splitlines()[0]
    page, _, _ = select_memory_page(
        selection[1].entries, query="short task", project_name=None, scope="all",
        budget_tokens=1, render=lambda *args: "unused", cursor=cursor, detail="full",
    )
    assert page[0].statement == selection[1].entries[0].statement
    assert receipt["index_only"] is True and receipt["returned_count"] == 0
    assert not selection[1].effects


def test_zero_matches_with_long_query_gives_bounded_empty_result_guidance(selection):
    selection[1].entries = []
    query = "未匹配的完整任务🧠" * 500
    receipt = {}
    result = inject(selection, current_task=query, budget_tokens=200, selection_receipt=receipt)
    assert result.startswith("# Memory candidates\nNo lexical candidates matched.")
    assert query not in result
    assert selection[1].searches == [{"query": query, "expand_long_query": True}]
    assert receipt == {"query_present": True, "matched_count": 0, "returned_count": 0,
                       "candidate_count": 0, "index_only": False}
    assert not selection[1].effects


def test_notice_cannot_exceed_original_budget_or_mark_any_memory_returned(selection):
    receipt = {}
    with pytest.raises(ValueError, match="^budget_tokens is too small to return a reading link\\.$"):
        inject(selection, current_task="长任务🧠" * 500, budget_tokens=1, selection_receipt=receipt)
    assert receipt == {} and not selection[1].effects


def test_other_page_value_error_propagates_unchanged(selection, monkeypatch):
    error = ValueError("Reading position belongs to a different query or scope.")

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(wake, "select_memory_page", reject)
    receipt = {}
    with pytest.raises(ValueError) as caught:
        inject(selection, current_task="short task", budget_tokens=500, selection_receipt=receipt)
    assert caught.value is error
    assert receipt == {} and not selection[1].effects


def test_no_query_does_not_browse_or_offer_an_empty_search(selection):
    receipt = {}
    output = inject(selection, budget_tokens=500, selection_receipt=receipt)
    assert "specific task when needed" in output and "Continue reading:" not in output
    assert not selection[1].searches
    assert receipt == {"query_present": False, "matched_count": None, "returned_count": 0, "index_only": False}
    assert not selection[1].effects


def test_no_query_still_rejects_invalid_budget(selection):
    with pytest.raises(ValueError, match="budget_tokens must be positive"):
        inject(selection, budget_tokens=0)
    assert not selection[1].searches and not selection[1].effects
