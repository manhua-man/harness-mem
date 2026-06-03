from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v22_docs_keep_manual_gate_open_while_packet_has_non_claude_gap() -> None:
    roadmap_v22x = (REPO_ROOT / "docs" / "roadmap-v22x.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-03 — Codex MCP smoke" in packet
    assert "## 2026-06-03 — Generic MCP JSON-RPC smoke" in packet
    assert "## 2026-06-03 — Cursor runtime stack evidence" in packet
    assert "## 2026-06-03 — Cursor agent run-log evidence" in packet
    assert "generic MCP client 路径" in packet
    assert "Cursor runtime stack" in packet
    assert "agent exec startup" in packet
    assert "mcp-router" in packet
    assert "wake.json" in packet
    assert "f:\\huiben\\bazi-apps" in packet
    assert "mcp__harness-mem__search_memory" in packet
    assert "mcp__harness-mem__timeline" in packet
    assert "full 12-scenario matrix 已补齐" not in packet
    assert "cross-client release gate" in roadmap_v22x
    assert "仍不能算闭环" in roadmap_v22x
    assert "agent exec startup" in roadmap_v22x
    assert "MCP cache" in roadmap_v22x
    assert "真实的 harness-mem MCP 调用 run log" in roadmap_v22x
    assert "v2.2 runtime / contract 已完成" in roadmap_v22x
    assert "v2.2.0 | runtime 已完成；手工 gate 未闭" in roadmap_status
    assert "已有 Codex + generic MCP 两条 non-Claude smoke" in roadmap_status
    assert "agent exec startup" in roadmap_status
    assert "工具 cache" in roadmap_status
    assert "真实的 Cursor agent run log" in roadmap_status
