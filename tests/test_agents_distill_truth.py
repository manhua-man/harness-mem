from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agents_distill_guidance_uses_auto_review_surface() -> None:
    agents_doc = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "session-distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true) -> final summary" in agents_doc
    assert "Agent 创建候选后，应通过 MCP `auto_review_candidates(project_name=<project>, apply=true)`" in agents_doc
    assert "repair/recheck 流里仍可显式使用 MCP `list_candidates` / `confirm_*` / `reject_*` 做逐项 drilldown" in agents_doc
    assert "session-distill -> suggest_* -> list_candidates -> auto_review_candidates/confirm/reject -> final summary" not in agents_doc
    assert "`prepare_session_distill -> suggest_* -> list_candidates -> auto_review_candidates/confirm/reject`" not in agents_doc
