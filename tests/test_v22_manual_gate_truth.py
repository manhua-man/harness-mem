from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v22_docs_keep_manual_gate_open_while_packet_has_non_claude_gap() -> None:
    roadmap_v22x = (REPO_ROOT / "docs" / "roadmap-v22x.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-03 — Codex MCP smoke" in packet
    assert "## 2026-06-03 — Generic MCP JSON-RPC smoke" in packet
    assert "generic MCP client 路径" in packet
    assert "full 12-scenario matrix 已补齐" not in packet
    assert "cross-client release gate" in roadmap_v22x
    assert "仍不能算闭环" in roadmap_v22x
    assert "v2.2 runtime / contract 已完成" in roadmap_v22x
    assert "v2.2.0 | runtime 已完成；手工 gate 未闭" in roadmap_status
    assert "已有 Codex + generic MCP 两条 non-Claude smoke" in roadmap_status
