from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v22_docs_keep_manual_gate_open_while_packet_has_non_claude_gap() -> None:
    roadmap_v22x = (REPO_ROOT / "docs" / "roadmap-v22x.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "Known gap: 非 Claude client (Codex / Cursor / generic MCP) 未跑" in packet
    assert "手工 cross-client release gate 尚未闭环" in roadmap_v22x
    assert "v2.2 runtime / contract 已完成" in roadmap_v22x
    assert "v2.2.0 | runtime 已完成；手工 gate 未闭" in roadmap_status
    assert "Run log 仍只有 Claude Code entry" in roadmap_status
