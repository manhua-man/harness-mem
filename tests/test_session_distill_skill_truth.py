from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_session_distill_skill_uses_auto_review_as_default_surface() -> None:
    skill_doc = _text("tools/session-distill/SKILL.md")

    assert "mcp__harness_mem__auto_review_candidates" in skill_doc
    assert "-> auto_review_candidates(apply=true)" in skill_doc
    assert "调用 MCP `auto_review_candidates(project_name=<project>, apply=true)`" in skill_doc
    assert "`list_candidates`、`confirm_*`、`reject_*` 仍可用于显式 review drilldown" in skill_doc
    assert "-> list_candidates" not in skill_doc
    assert "-> AI auto-review and low-risk confirm/reject" not in skill_doc


def test_plugin_readme_distill_row_mentions_auto_review_candidates() -> None:
    plugin_readme = _text("plugins/harness-mem/README.md")

    assert "apply `auto_review_candidates` as the default low-risk review surface" in plugin_readme
