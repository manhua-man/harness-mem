from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_best_practices_uses_auto_review_as_default_distill_surface() -> None:
    best_practices = _text("docs/best-practices.md")

    assert "MCP (`auto_review_candidates`，必要时查看 `applied_decisions`)" in best_practices
    assert "`/hm:distill` 应在同一轮调用 MCP `auto_review_candidates(project_name=<project>, apply=true)`" in best_practices
    assert "| **管理** | `auto_review_candidates` |" in best_practices
    assert "`/hm:distill` 同一轮读取 `list_candidates`" not in best_practices
