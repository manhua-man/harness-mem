from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_explicitly_records_remaining_strong_evidence_gaps() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")

    assert "UI 级 `S10` cross-client pair（如 Codex→Claude、Cursor→Claude）" in packet
    assert "full matrix 里尚未补齐的 `S4 / S5 / S7 / S11`" in packet
    assert "`harness_mem/integration` 工作区上的真实 Cursor packet scenario run log" in packet
    assert "而不只是 runtime / cache / transcript 旁证" in packet
    assert "Current evidence status:" in packet
    assert "这条证据仍**不是** Codex / Cursor / Claude 的 client-facing transcript" in packet
    assert "还没有覆盖" in packet

    assert "尤其是 `S4/S5/S7`、UI 级 cross-client pair，以及" in roadmap_status
    assert "`harness_mem/integration` 工作区上的真实 Cursor packet scenario run log" in roadmap_status
    assert "这仍不等于 full matrix 的 `S4/S5/S7/S11` 或 UI 级 `S10` cross-client pair 已全部补齐" in roadmap_status
