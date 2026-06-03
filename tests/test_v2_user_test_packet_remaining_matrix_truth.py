from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_explicitly_records_remaining_strong_evidence_gaps() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_status = " ".join(
        (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8").split()
    )

    assert "当前已新增一条直接对应 packet 单元格的 UI 级 `S10` pair：`Codex app → Claude Code`" in packet
    assert "当前还已有一条真实 `Cursor / user-mcp-router` wake transcript" in packet
    assert "Cursor 侧的 `S10` 扩展证据（如 `Cursor→Claude` 或 integration-workspace Cursor pair）" in packet
    assert "full matrix 里尚未补齐的 `S4 / S5 / S7 / S11`" in packet
    assert "`harness_mem/integration` 工作区上的真实 Cursor packet scenario run log" in packet
    assert "而不只是 runtime / cache / transcript 旁证" in packet
    assert "Current evidence status:" in packet
    assert "这条证据仍**不是** Codex / Cursor / Claude 的 client-facing transcript" in packet
    assert "还没有 `Cursor -> Claude`" in packet

    assert "还已经拿到了一条直接对应 packet `S10` 单元格的跨客户端 client transcript" in roadmap_status
    assert "真实 `Cursor / user-mcp-router` wake transcript" in roadmap_status
    assert "`S5/S7`" in roadmap_status
    assert "`S4/S11` 的 client-facing transcript" in roadmap_status
    assert "workspace provenance" in roadmap_status
    assert "`harness_mem/integration` Cursor packet run log" in roadmap_status
    assert "Claude 自动化读端" in roadmap_status
    assert "integration-workspace Cursor packet run log 已完成" in roadmap_status
