"""Retrieval ranks the report itself while returning its attribution."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp.read_projection import project_memory_entries
from harness_mem.read_knowledge import search_current_knowledge


def test_report_boilerplate_does_not_create_matches_or_hide_source_boundary():
    report = SourceReport(
        speaker="assistant", period="2026-10-01T00:00:00Z", session_id="session",
        source_id="source", source_revision="revision", exchange_indexes=[1],
        text="管线失败时先检查素材保存，确认资源后重试。",
    )
    entry = KnowledgeEntry(
        project_name="other", module_path=["video"], source_report=report,
        title=report.render_title(), statement=report.render_statement(),
    )
    store = SimpleNamespace(
        list_entries=AsyncMock(return_value=[entry]), known_projects=AsyncMock(return_value=["other"]),
    )
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store))

    # These words occur only in every report's fixed English attribution.
    noise = asyncio.run(search_current_knowledge(backend, query="current user"))
    found = asyncio.run(search_current_knowledge(backend, query="素材保存"))
    by_complete_title = asyncio.run(search_current_knowledge(backend, query=entry.title))
    by_complete_statement = asyncio.run(search_current_knowledge(backend, query=entry.statement))
    by_displayed_statement = asyncio.run(search_current_knowledge(backend, query=report.readable_statement()))

    assert noise == []
    assert found == [entry]
    assert by_complete_title == [entry]
    assert by_complete_statement == [entry]
    assert by_displayed_statement == [entry]
    projected = project_memory_entries(found, include_project=True)[0]
    assert projected["statement"] == report.readable_statement()
    assert "助手记述" in projected["statement"]
    assert "未独立核实" in projected["statement"]
    assert "不能据此认定当前事实或用户授权" in projected["statement"]
    assert projected["statement"].endswith(report.text)
    assert report.period in projected["statement"]
    assert "Source-scoped report" not in projected["statement"]


def test_actual_report_text_can_still_match_attribution_words():
    report = SourceReport(
        speaker="user", period="2026-10-01T00:00:00Z", session_id="session",
        source_id="source", source_revision="revision", exchange_indexes=[1],
        topic_title="Current User session isolation",
        text="Current User sessions must stay isolated across accounts.",
    )
    entry = KnowledgeEntry(
        project_name="other", module_path=["accounts"], source_report=report,
        title=report.render_title(), statement=report.render_statement(),
    )
    store = SimpleNamespace(
        list_entries=AsyncMock(return_value=[entry]), known_projects=AsyncMock(return_value=["other"]),
    )
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store))

    found = asyncio.run(search_current_knowledge(backend, query="Current User session"))
    assert found == [entry]
