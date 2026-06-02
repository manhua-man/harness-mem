from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_best_practices_mentions_first_class_wake_surface() -> None:
    best_practices = _text("docs/best-practices.md")

    assert "| **读取** | `wake` |" in best_practices
    assert "MCP `wake(project_name=<project>)` 工具调用一等 wake-up surface" in best_practices
    assert "`renderer=\"compact\"`" in best_practices
    assert "`include_skill_hints=true`" in best_practices
