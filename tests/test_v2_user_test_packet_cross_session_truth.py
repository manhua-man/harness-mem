from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_generic_mcp_cross_session_truth_visibility() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Generic MCP cross-session confirmed truth visibility" in packet
    assert "harness-mem version: 2.9.58" in packet
    assert "Project: `v2958-cross-session`" in packet
    assert "two independent MCP server processes" in packet
    assert "Pass: near-neighbor S10" in packet
    assert "confirm_memory_entry(entry_id=...)" in packet
    assert "wake(project_name=\"v2958-cross-session\", no_auto_ingest=true)" in packet
    assert "Cross-session confirmed truth should surface in wake output." in packet
    assert "两个独立 generic MCP 会话" in packet
