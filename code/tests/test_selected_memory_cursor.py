"""Exact reads must fail rather than open another selected memory."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.mcp.read_projection import (
    make_selected_memory_cursor,
    memory_candidate_projector,
    reading_tokens,
    select_memory_page,
)


@pytest.fixture
def entries():
    return [
        KnowledgeEntry(
            id=f"entry-{position}", project_name=project,
            title=f"Reading rule {position}", module_path=["Reading"],
            statement=f"Complete fact {position}. " + "保留原文中的条件。" * 80 + "最后条件。",
        )
        for position, project in enumerate(["alpha", "beta", "alpha"])
    ]


def _encode(values):
    return base64.urlsafe_b64encode(
        json.dumps(values, separators=(",", ":")).encode("utf-8")
    ).decode().rstrip("=")


def _decode(cursor):
    return json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))


def _legacy_cursor(entries, position):
    # Reproduce the already-public three-field wire format, independently of
    # the new selected-cursor constructor.
    request = hashlib.sha256(json.dumps(
        ["all", None, "reading"], ensure_ascii=False,
    ).encode("utf-8")).hexdigest()[:24]
    revision = hashlib.sha256(json.dumps([
        [entry.id, entry.project_name, entry.title, entry.statement, entry.module_path]
        for entry in entries
    ], ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
    return _encode([position, request, revision])


def _selected(entries, position=1):
    return make_selected_memory_cursor(
        entries, query="reading", project_name=None, scope="all", position=position,
    )


def _render(page, metadata, index):
    return {"memories": [
        {"title": entry.title, **({} if index else {"statement": entry.statement})}
        for entry in page
    ], **metadata}


def _read(entries, cursor, **overrides):
    return select_memory_page(entries, **{
        "query": "reading", "project_name": None, "scope": "all",
        "budget_tokens": 1, "render": _render, "cursor": cursor, "detail": "full",
        **overrides,
    })


def test_selected_cursor_preserves_legacy_binding_and_adds_exact_identity(entries):
    selected = _decode(_selected(entries))
    assert selected[:3] == _decode(_legacy_cursor(entries, 1))
    assert selected[3:5] == [entries[1].id, entries[1].project_name]
    assert isinstance(selected[5], str) and selected[5]


@pytest.mark.parametrize("availability_only", [False, True])
def test_selected_cursor_opens_second_complete_fact_even_over_budget(entries, availability_only):
    page, metadata, index = _read(
        entries, _selected(entries), availability_only=availability_only,
    )
    assert page == [entries[1]]
    assert page[0].statement == entries[1].statement
    assert page[0].statement.endswith("最后条件。")
    assert metadata["detail"] == "full"
    assert index is False


def test_selected_cursor_requires_explicit_full_read(entries):
    with pytest.raises(ValueError, match="requires detail=full"):
        _read(entries, _selected(entries), detail="auto")


@pytest.mark.parametrize("overrides", [
    {"query": "another question"},
    {"scope": "project", "project_name": "alpha"},
    {"project_name": "alpha"},
])
def test_selected_cursor_rejects_another_query_or_scope(entries, overrides):
    with pytest.raises(ValueError, match="different query or scope"):
        _read(entries, _selected(entries), **overrides)


@pytest.mark.parametrize("field,value", [
    ("statement", "A revised condition."),
    ("title", "A revised title"),
    ("module_path", ["Changed"]),
    ("id", "replacement-entry"),
    ("project_name", "another-project"),
])
def test_selected_cursor_rejects_result_revision_changes(entries, field, value):
    cursor = _selected(entries)
    # Even another entry changing invalidates the complete ordered result set.
    changed = [entries[0].model_copy(update={field: value}), *entries[1:]]
    with pytest.raises(ValueError, match="results changed"):
        _read(changed, cursor)


@pytest.mark.parametrize("change", ["reorder", "remove_selected", "empty"])
def test_selected_cursor_never_retargets_after_result_set_changes(entries, change):
    cursor = _selected(entries)
    changed = {
        "reorder": list(reversed(entries)),
        "remove_selected": [entries[0], entries[2]],
        "empty": [],
    }[change]
    with pytest.raises(ValueError, match="results changed"):
        _read(changed, cursor)


@pytest.mark.parametrize("index,value", [(3, "another-id"), (4, "another-project")])
def test_selected_cursor_checks_identity_separately_from_the_result_revision(entries, index, value):
    decoded = _decode(_selected(entries))
    decoded[index] = value
    with pytest.raises(ValueError, match="identity changed"):
        _read(entries, _encode(decoded))


def test_selected_cursor_rejects_changed_typed_report_source_with_same_rendered_body():
    from harness_mem.core.schemas.source_report import SourceReport

    report = SourceReport(
        speaker="assistant", period="2026-10-01T00:00:00Z", session_id="session",
        source_id="source-one", source_revision="revision", exchange_indexes=[1],
        text="A bounded earlier report.", topic_title="Report topic",
    )
    entry = KnowledgeEntry(
        id="report", project_name="demo", title=report.render_title(),
        statement=report.render_statement(), module_path=["test"], source_report=report,
    )
    cursor = _selected([entry], position=0)
    changed_report = report.model_copy(update={"source_id": "source-two"})
    changed_entry = entry.model_copy(update={"source_report": changed_report})
    with pytest.raises(ValueError, match="Selected memory changed"):
        _read([changed_entry], cursor)


@pytest.mark.parametrize("position", [-1, True, 3, 1.5])
def test_selected_cursor_constructor_rejects_invalid_positions(entries, position):
    with pytest.raises(ValueError, match="outside the current results"):
        _selected(entries, position)


def test_selected_cursor_rejects_out_of_range_encoded_position(entries):
    decoded = _decode(_selected(entries))
    decoded[0] = len(entries)
    with pytest.raises(ValueError, match="outside the current results"):
        _read(entries, _encode(decoded))


@pytest.mark.parametrize("index,value", [(3, None), (4, "")])
def test_selected_cursor_rejects_malformed_identity(entries, index, value):
    decoded = _decode(_selected(entries))
    decoded[index] = value
    with pytest.raises(ValueError, match="Reading position is invalid"):
        _read(entries, _encode(decoded))


def test_legacy_three_field_cursor_still_opens_its_position(entries):
    page, metadata, index = _read(entries, _legacy_cursor(entries, 1))
    assert page == [entries[1]]
    assert metadata["detail"] == "full"
    assert index is False


def test_legacy_changed_revision_still_restarts_at_first_page(entries):
    cursor = _legacy_cursor(entries, 1)
    changed = [entries[0].model_copy(update={"statement": "Updated first fact."}), *entries[1:]]
    page, metadata, index = _read(changed, cursor)
    assert page == [changed[0]]
    assert metadata["message"] == "Memory changed; showing the current first page."
    assert index is False


def test_legacy_end_position_remains_valid(entries):
    page, metadata, index = _read(entries, _legacy_cursor(entries, len(entries)))
    assert page == []
    assert metadata == {"detail": "full"}
    assert index is False


def _cost_page(entries, query, budget, incremental):
    cards = memory_candidate_projector(entries, query=query, project_name=None, scope="all",
                                       whole_if_cheaper=True)
    seen = set()

    def render(page, metadata, index):
        seen.update(entry.id for entry in page)
        return {"query": query, "memories": cards(page, index), **metadata}

    try:
        page, metadata, index = select_memory_page(entries, query=query, project_name=None,
            scope="all", budget_tokens=budget, render=render, incremental=incremental)
    except ValueError as error:
        return (str(error),), seen
    return ([entry.id for entry in page], metadata, index, reading_tokens(render(page, metadata, index))), seen


@pytest.mark.parametrize("count", [0, 3, 18])
@pytest.mark.parametrize("budget", [100, 300, 600, 1200, 2400])
def test_incremental_json_pages_match_eager_budget_and_cursor_behavior(count, budget):
    entries = [KnowledgeEntry(id=f"incremental-{index}", project_name="alpha", title=f"Rule {index}",
        statement=("Keep the recovery copy until both checks pass." if index % 2 else "条件必须全部保留。" * 120),
        module_path=["Recovery"]) for index in range(count)]
    query = "完整的任务问题需要保留。" * 15
    eager, _ = _cost_page(entries, query, budget, False)
    incremental, _ = _cost_page(entries, query, budget, True)
    assert incremental == eager


def test_incremental_json_page_does_not_project_the_entire_library():
    entries = [KnowledgeEntry(id=f"lazy-{index}", project_name="alpha", title=f"Rule {index}",
        statement="Keep the original backup until restoration is verified.", module_path=["Recovery"])
        for index in range(300)]
    eager, eager_seen = _cost_page(entries, "backup", 600, False)
    incremental, incremental_seen = _cost_page(entries, "backup", 600, True)
    assert incremental == eager
    assert len(eager_seen) == len(entries)
    assert len(incremental_seen) < len(entries) // 5


def test_incremental_page_can_fit_all_facts_when_a_partial_continuation_would_not():
    entries = [KnowledgeEntry(id=f"whole-{index}", project_name="alpha", title=f"Rule {index}",
        statement="Keep the backup.", module_path=["Recovery"]) for index in range(3)]
    query = "问" * 150
    cards = memory_candidate_projector(entries, query=query, project_name=None, scope="all", whole_if_cheaper=True)
    budget = reading_tokens({"query": query, "memories": cards(entries)})
    eager, _ = _cost_page(entries, query, budget, False)
    incremental, _ = _cost_page(entries, query, budget, True)
    assert incremental == eager
    assert incremental[0] == [entry.id for entry in entries]
    assert incremental[1] == {}
