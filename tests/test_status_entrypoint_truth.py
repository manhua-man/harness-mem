from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_hm_status_command_uses_mcp_status_surface() -> None:
    status_doc = _text("plugins/harness-mem/commands/hm/status.md")

    assert "调 MCP `get_project_status`" in status_doc
    assert "`phase` / `suggested_slash` / `reason`" in status_doc
    assert "`repair_hint` / `repair_reason`" in status_doc
    assert "get_project_profile(project_name=<project>)" not in status_doc
    assert "list_candidates(project_name=<project>, status=\"pending\", limit=20)" not in status_doc
    assert "timeline(project_name=<project>, limit=5)" not in status_doc


def test_mcp_spec_status_example_uses_triage_fields() -> None:
    mcp_spec = _text("openspec/specs/mcp/spec.md")
    start = mcp_spec.index("#### Scenario: Agent checks project status without CLI")
    end = mcp_spec.index("### Requirement: list_candidates 审核入口")
    status_example = mcp_spec[start:end]

    assert "MCP -> get_project_status({" in status_example
    assert '"phase": "ready"' in status_example
    assert '"suggested_slash": "/hm:wake"' in status_example
    assert '"reason": "Project has usable memory context."' in status_example
    assert '"repair_hint": "/hm:review"' in status_example
    assert '"repair_reason": "Pending candidates remain from earlier review work."' in status_example
