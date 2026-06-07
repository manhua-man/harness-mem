from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_explicitly_records_remaining_strong_evidence_gaps() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "当前已新增一条直接对应 packet 单元格的 UI 级 `S10` pair：`Codex app → Claude Code`" in packet
    assert "当前还已有一条真实 `Cursor / user-mcp-router` wake transcript" in packet
    assert "user-mcp-router 刷新后已经能返回当前 repo 的新 wake shape" in packet
    assert "Client-facing S7 transcript" in packet
    assert "Client-facing S11 transcript" in packet
    assert "Cursor 侧的 `S10` 扩展证据（如 `Cursor→Claude` 或 integration-workspace Cursor pair）" in packet
    assert "full matrix 里尚未补齐的 `S4`" in packet
    assert "`harness_mem/integration` 工作区上的真实 Cursor packet scenario run log" in packet
    assert "而不只是 runtime / cache / transcript 旁证" in packet
    assert "Current evidence status:" in packet
    assert "这条证据仍**不是** Codex / Cursor / Claude 的 client-facing transcript" in packet
    assert "还没有 `Cursor -> Claude`" in packet
