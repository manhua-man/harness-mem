from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_wake_renderer_confirmed_truth_readback() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Wake renderer confirmed-truth readback" in packet
    assert "Pass: near-neighbor S10 read-side evidence" in packet
    assert "`cmd_wake_up(project_name=\"v2961-wake-renderer-truth\", no_auto_ingest=true)` returned success" in packet
    assert "# Essential Truth  (L1 · confirmed current)" in packet
    assert "Wake renderer should surface confirmed truth written earlier." in packet
    assert "它仍**不等于** packet 单元格要求的 UI 级 cross-client pair" in packet
