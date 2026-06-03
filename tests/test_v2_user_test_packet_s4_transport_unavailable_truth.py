from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_generic_mcp_transport_unavailable_repro() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Generic MCP transport unavailable repro" in packet
    assert "python -m harness_mem.mcp.server_missing" in packet
    assert "subprocess exited before any JSON-RPC handshake" in packet
    assert "No module named harness_mem.mcp.server_missing" in packet
    assert "Pass: lower-layer S4 evidence" in packet
    assert "它仍**不等于** packet 单元格要求的完整 client-facing 行为" in packet
    assert "`harness-mem doctor`" in packet

    assert "目前又新增了一条 generic MCP 的底层 S4 repro" in roadmap_status
    assert "错误启动目标会让 server 在握手前直接失败" in roadmap_status
