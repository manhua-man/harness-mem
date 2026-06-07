from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_codex_to_claude_ui_s10_pair() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_v29 = " ".join(
        (REPO_ROOT / "docs" / "roadmap-v29.md").read_text(encoding="utf-8").split()
    )

    assert "## 2026-06-04 — Codex app -> Claude Code cross-client confirmed truth visibility" in packet
    assert "Clients: Codex app (write-side) + Claude Code (read-side)" in packet
    assert "Pass: S10 UI-level cross-client pair (`Codex app -> Claude Code`)" in packet
    assert "`set_active_project`" in packet
    assert "`suggest_memory_entry`" in packet
    assert "`confirm_memory_entry`" in packet
    assert "S10 cross-client manual sentinel 2026-06-04 01." in packet
    assert "read-side final output returned the exact truth line" in packet
    assert "PostToolUse:mcp__harness_mem__wake" in packet
    assert "这条 entry 是一条**直接对应 packet `S10` 单元格**的真实 client transcript" in packet

    assert "direct UI-level `S10` pair transcript" in roadmap_v29
    assert "write-side = `Codex app`" in roadmap_v29
    assert "read-side = `Claude Code`" in roadmap_v29
