from pathlib import Path

import pytest

from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.qualification.archive_cohort_acceptance import (
    _assert_isolated_paths,
    _quality_findings,
)
from harness_mem.knowledge_renderer import render_knowledge_markdown


def test_quality_accepts_clean_title_statement_projection() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["会话生命周期与 Hook"],
            title="Hook 终态绑定实际作业",
            statement="Hook 回执必须对应同一会话的实际作业与最终 Note。",
        )
    ]
    markdown = render_knowledge_markdown("harness-mem", entries)

    quality = _quality_findings(entries, markdown)

    assert quality["passed"] is True
    assert quality["projection_keys"] == ["statement", "title"]
    assert quality["forbidden_headings"] == []


def test_quality_accepts_one_obligation_that_lists_required_fields() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["会话接入与生命周期"],
            title="最终会话审查记录字段",
            statement=(
                "最终会话审查记录必须包含会话标识、作业标识、"
                "Provider 回执、Note 路径和终态。"
            ),
        )
    ]

    quality = _quality_findings(
        entries,
        render_knowledge_markdown("harness-mem", entries),
    )

    assert quality["passed"] is True
    assert quality["broad_item_warnings"] == []


def test_quality_rejects_multiple_pipeline_actions_as_one_item() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["归纳吸收"],
            title="完整处理管线",
            statement="抓取原文、保存证据、规范化候选、验证协议、发布知识。",
        )
    ]

    quality = _quality_findings(
        entries,
        render_knowledge_markdown("harness-mem", entries),
    )

    assert quality["passed"] is False
    assert quality["broad_item_warnings"][0]["title"] == "完整处理管线"


def test_quality_rejects_internal_heading_and_audit_leak() -> None:
    entries = [
        KnowledgeEntry(
            project_name="harness-mem",
            module_path=["稳定操作规则"],
            title="候选处理",
            statement="普通结果不得展示 candidate_id。",
        )
    ]
    markdown = render_knowledge_markdown("harness-mem", entries)

    quality = _quality_findings(entries, markdown)

    assert quality["passed"] is False
    assert quality["forbidden_headings"] == ["稳定操作规则"]
    assert quality["leaked_markers"] == ["candidate_id"]


def test_acceptance_output_must_not_overlap_protected_roots(
    tmp_path: Path,
) -> None:
    source = tmp_path / "archives"
    real_data = tmp_path / "real-data"
    real_notes = tmp_path / "real-notes"

    with pytest.raises(ValueError, match="must not overlap"):
        _assert_isolated_paths(
            output_root=real_data / "nested",
            source_archive_dir=source,
            real_data_dir=real_data,
            real_notes_dir=real_notes,
        )

    _assert_isolated_paths(
        output_root=tmp_path / "isolated",
        source_archive_dir=source,
        real_data_dir=real_data,
        real_notes_dir=real_notes,
    )
