from datetime import datetime, timezone
from pathlib import Path

import pytest

import harness_mem.knowledge_renderer as renderer_module
from harness_mem.core.schemas import (
    KnowledgeEntry,
    KnowledgeSource,
    KnowledgeVersion,
    ProjectKnowledgeSourceRef,
)
from harness_mem.knowledge_renderer import render_knowledge_markdown


VERIFIED_AT = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _entry(
    *,
    entry_id: str,
    module_path: list[str],
    title: str,
    statement: str,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=entry_id,
        project_name="harness-mem",
        module_path=module_path,
        title=title,
        statement=statement,
        verified_at=VERIFIED_AT,
        revision=2,
        created_at=VERIFIED_AT,
        updated_at=VERIFIED_AT,
    )


def test_current_knowledge_payload_is_minimal_and_round_trips() -> None:
    entry = _entry(
        entry_id="knowledge-hook",
        module_path=["会话生命周期与 Hook"],
        title="Hook 终态绑定实际作业",
        statement="完成回执必须对应同一会话的作业与 Session Note。",
    )

    payload = entry.to_dict()

    assert set(payload) == {
        "id",
        "project_name",
        "module_path",
        "title",
        "statement",
        "verified_at",
        "revision",
        "created_at",
        "updated_at",
    }
    assert "source_refs" not in payload
    assert "claim_kind" not in payload
    assert "topic_path" not in payload
    assert KnowledgeEntry.from_dict(payload) == entry


def test_current_knowledge_rejects_audit_fields_but_reads_transitional_rows() -> None:
    base = _entry(
        entry_id="knowledge-clean",
        module_path=["归纳吸收"],
        title="正式知识保持干净",
        statement="正式知识不携带候选或审计字段。",
    ).to_dict()

    with pytest.raises(ValueError):
        KnowledgeEntry.model_validate({**base, "distill_job_id": "job-1"})

    transitional = dict(base)
    transitional["topic_path"] = transitional.pop("module_path")
    transitional["source_refs"] = [{"label": "旧来源", "target": "old.md"}]
    transitional["claim_kind"] = "procedure"
    restored = KnowledgeEntry.from_dict(transitional)

    assert restored.module_path == ["归纳吸收"]
    assert restored.to_dict() == base


def test_minimal_source_and_bounded_version_are_separate_records() -> None:
    source = KnowledgeSource(
        id="source-1",
        knowledge_id="knowledge-1",
        project_name="harness-mem",
        source_kind="repository_file",
        locator="harness_mem/host_entry/__main__.py",
        content_sha256="a" * 64,
        verified_at=VERIFIED_AT,
    )
    version = KnowledgeVersion(
        id="version-1",
        knowledge_id="knowledge-1",
        project_name="harness-mem",
        revision=1,
        module_path=["会话生命周期与 Hook"],
        title="旧标题",
        statement="这是可供一次有界撤销使用的旧正文。",
        verified_at=VERIFIED_AT,
        recorded_at=VERIFIED_AT,
    )
    input_ref = ProjectKnowledgeSourceRef(
        label="相关实现",
        target="harness_mem/host_entry/__main__.py",
        kind="repository_file",
        digest="sha256:" + "a" * 64,
    )

    assert source.to_dict()["knowledge_id"] == "knowledge-1"
    assert version.to_dict()["revision"] == 1
    assert input_ref.kind == "repository_file"
    assert input_ref.digest == "sha256:" + "a" * 64


def test_normal_markdown_is_deterministic_grouped_unicode_and_hides_internal_data() -> None:
    entries = [
        _entry(
            entry_id="secret-id-b",
            module_path=["归纳吸收", "知识形态"],
            title="标题与正文",
            statement="默认结果只展示自然模块、标题与正文。",
        ),
        _entry(
            entry_id="secret-id-a",
            module_path=["会话生命周期与 Hook"],
            title="Hook 终态绑定实际作业",
            statement="完成回执必须对应同一会话的实际作业。",
        ),
    ]

    rendered = render_knowledge_markdown("harness-mem", reversed(entries))

    assert rendered == render_knowledge_markdown("harness-mem", entries)
    assert rendered == (
        "# harness-mem 会话蒸馏知识库\n"
        "\n"
        "## 会话生命周期与 Hook\n"
        "- **Hook 终态绑定实际作业**：完成回执必须对应同一会话的实际作业。\n"
        "\n"
        "## 归纳吸收\n"
        "\n"
        "### 知识形态\n"
        "- **标题与正文**：默认结果只展示自然模块、标题与正文。\n"
    )
    assert "secret-id" not in rendered
    assert "revision" not in rendered
    assert "verified" not in rendered


def test_empty_render_and_full_render_are_deterministic() -> None:
    entry = _entry(
        entry_id="knowledge-1",
        module_path=["检索与使用"],
        title="默认检索保持干净",
        statement=r"路径 C:\repo 与 *标记* 仅作为正文。",
    )
    source = KnowledgeSource(
        id="hidden-source-id",
        knowledge_id=entry.id,
        project_name="harness-mem",
        source_kind="repository_file",
        locator="tests/[contract].py",
        content_sha256=None,
        verified_at=VERIFIED_AT,
    )

    assert render_knowledge_markdown("空项目", []) == "# 空项目 会话蒸馏知识库\n"
    rendered = render_knowledge_markdown(
        "harness-mem",
        [entry],
        include_details=True,
        sources_by_knowledge_id={entry.id: [source]},
    )

    assert "verified 2026-08-19" in rendered
    assert "source repository_file: tests/\\[contract\\].py" in rendered
    assert "knowledge-1" not in rendered
    assert "hidden-source-id" not in rendered
    assert r"C:\\repo" in rendered
    assert r"\*标记\*" in rendered


def test_markdown_projection_has_no_authority_parser_or_write_path() -> None:
    assert not Path("harness_mem/storage/project_knowledge_base.py").exists()
    for forbidden_name in ("parse", "read", "replace", "write", "canonical_path"):
        assert not hasattr(renderer_module, forbidden_name)


def test_renderer_rejects_cross_project_entries() -> None:
    entry = _entry(
        entry_id="knowledge-1",
        module_path=["检索"],
        title="按项目隔离",
        statement="普通总览不能混入另一个项目。",
    ).model_copy(update={"project_name": "another-project"})

    with pytest.raises(ValueError, match="rendered project"):
        render_knowledge_markdown("harness-mem", [entry])
