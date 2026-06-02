from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_hm_wake_command_uses_mcp_wake_surface() -> None:
    wake_doc = _text("plugins/harness-mem/commands/hm/wake.md")

    assert "调 MCP `wake`" in wake_doc
    assert "renderer=\"compact\"" in wake_doc
    assert "include_skill_hints=true" in wake_doc
    assert "get_project_profile(project_name=<project>)" not in wake_doc
    assert "get_task_handoffs(project_name=<project>, limit=5)" not in wake_doc
    assert "get_confirmed_rules(project_name=<project>)" not in wake_doc
    assert "timeline(project_name=<project>, limit=10)" not in wake_doc


def test_repo_local_skill_uses_mcp_wake_for_wake_up() -> None:
    skill_doc = _text("plugins/harness-mem/skills/harness-mem/SKILL.md")

    assert "call `wake(project_name=<project>)` instead of manually stitching low-level read tools" in skill_doc.lower()
    assert "call `get_project_profile`, `get_task_handoffs`, `get_confirmed_rules`, and `timeline`." not in skill_doc
