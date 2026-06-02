from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_hm_distill_command_uses_auto_review_surface() -> None:
    distill_doc = _text("plugins/harness-mem/commands/hm/distill.md")

    assert "mcp__harness_mem__auto_review_candidates" in distill_doc
    assert "调 MCP `auto_review_candidates`" in distill_doc
    assert "`apply=true`" in distill_doc
    assert "调 MCP `list_candidates`" not in distill_doc
    assert "AI 可以直接调用对应 MCP 工具处理低风险项" not in distill_doc


def test_repo_local_skill_uses_auto_review_by_default() -> None:
    skill_doc = _text("plugins/harness-mem/skills/harness-mem/SKILL.md")

    assert (
        "call `auto_review_candidates(project_name=<project>, apply=true)` as the default shipped review surface"
        in skill_doc.lower()
    )
    assert "when available" not in skill_doc.lower()
    assert "or call `list_candidates(project_name=<project>, status=\"pending\")`" not in skill_doc


def test_mcp_spec_distill_example_uses_auto_review_surface() -> None:
    mcp_spec = _text("openspec/specs/mcp/spec.md")
    start = mcp_spec.index("#### Scenario: Agent finishes distill with auto-review instead of asking for `/hm:review`")
    end = mcp_spec.index("#### Scenario: Agent checks project status without CLI")
    distill_example = mcp_spec[start:end]

    assert "MCP -> auto_review_candidates({" in distill_example
    assert '"apply": true' in distill_example
    assert '"applied_decisions": [' in distill_example
    assert "MCP -> confirm_memory_entry" not in distill_example
    assert "MCP -> reject_rule" not in distill_example
