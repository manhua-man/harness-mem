"""Readable report bodies retain boundaries and still select exact current rows."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.commands.distill_result import project_distill_result
from harness_mem.commands.knowledge_assimilation import KnowledgeTargetError, resolve_knowledge_targets
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.core.schemas.source_report import SourceReport, readable_knowledge_statement
from harness_mem.mcp.read_projection import project_memory_entries


def report_entry(**changes):
    fields = dict(speaker="assistant", period="2026-10-30T03:39:04.317Z",
                  session_id="private-session", source_id="private-source",
                  source_revision="private-revision", exchange_indexes=[2],
                  topic_title="代理端口检查", text="当时端口为 17890；复用前须重新核对当前配置。")
    fields.update(changes)
    report = SourceReport(**fields)
    return KnowledgeEntry(project_name="proxy", module_path=["diagnostics"],
                          title=report.render_title(), statement=report.render_statement(),
                          source_report=report)


@pytest.mark.parametrize("speaker", ["assistant", "user"])
def test_display_preserves_complete_account_date_and_boundary_without_mutating_storage(speaker):
    entry = report_entry(speaker=speaker)
    before = entry.to_dict()
    shown = project_memory_entries([entry], include_project=True)[0]
    assert shown["statement"].endswith(entry.source_report.text)
    assert entry.source_report.period in shown["statement"]
    assert ("助手记述" if speaker == "assistant" else "用户记述") in shown["statement"]
    assert "未独立核实" in shown["statement"] and "用户授权" in shown["statement"]
    assert "private-" not in str(shown)
    assert len(shown["statement"]) < len(entry.statement)
    assert entry.to_dict() == before
    assert KnowledgeEntry.from_dict(before).to_dict() == before
    assert readable_knowledge_statement(entry.statement, before["source_report"]) == shown["statement"]
    result = project_distill_result(
        [{"disposition": "add", "canonical_truth_ids": [entry.id]}], {entry.id: before})
    assert result["knowledge_changes"][0]["statement"] == shown["statement"]


def test_unknown_date_and_english_account_are_not_invented_or_translated():
    entry = report_entry(period="unknown", topic_title="Port check",
                         text="The recorded port was 17890; check the current configuration before reuse.")
    shown = project_memory_entries([entry])[0]["statement"]
    assert "session unknown" in shown
    assert "Assistant account" in shown
    assert "not independently established as current fact or user approval" in shown
    assert shown.endswith(entry.source_report.text)
    assert "2026" not in shown


@pytest.mark.parametrize("problem", ["missing", "invalid", "mismatched"])
def test_arbitrary_prose_is_never_stripped_by_wrapper_detection(problem):
    entry = report_entry()
    report = None if problem == "missing" else {} if problem == "invalid" else entry.source_report
    statement = "Source-scoped report — this is literal prose and must remain intact."
    assert readable_knowledge_statement(statement, report) == statement


@pytest.mark.parametrize("selection", ["display", "canonical"])
def test_exact_displayed_or_existing_body_resolves_same_current_entry(selection):
    entry = report_entry()
    store = SimpleNamespace(list_entries=AsyncMock(return_value=[entry]))
    before = entry.to_dict()
    target = project_memory_entries([entry], include_project=True, include_modules=True)[0]
    if selection == "canonical":
        target["statement"] = entry.statement
    assert asyncio.run(resolve_knowledge_targets(store, project_name="proxy", target_knowledge=[target])) == [entry.id]
    assert entry.to_dict() == before


@pytest.mark.parametrize("problem", ["changed", "ambiguous", "foreign"])
def test_readable_selection_does_not_weaken_missing_ambiguous_or_scope_checks(problem):
    original = report_entry()
    target = project_memory_entries([original], include_project=True)[0]
    entries = [original]
    if problem == "changed":
        entries = [report_entry(text="端口已经改变；复用前须重新核对当前配置。")]
    elif problem == "ambiguous":
        entries.append(report_entry(source_id="another-private-source"))
    else:
        target["project_name"] = "foreign"
    store = SimpleNamespace(list_entries=AsyncMock(return_value=entries))
    with pytest.raises(KnowledgeTargetError):
        asyncio.run(resolve_knowledge_targets(store, project_name="proxy", target_knowledge=[target]))
