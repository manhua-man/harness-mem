from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_points_at_main_daily_workflow_spec() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "`openspec/specs/daily-workflow/spec.md`" in packet
    assert "`openspec/changes/v220-ai-ide-entry-loop/specs/daily-workflow/spec.md`" not in packet
    assert "必要时 `openspec/changes/<change>/specs/...`（spec 真值变化）" not in packet
    assert "默认看 `openspec/specs/...`（当前主 spec 真值）" in packet
    assert "只有确实存在 active change proposal 时，才下钻 `openspec/changes/<change>/specs/...`" in packet
    assert "Codex CLI 当前版本所支持的 MCP 配置写法" not in packet
    assert "repo 当前维护并验证的 stdio 契约" in packet
