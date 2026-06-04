from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_s7_and_s11_client_facing_transcripts() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_status = " ".join(
        (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8").split()
    )
    roadmap_v29 = " ".join(
        (REPO_ROOT / "docs" / "roadmap-v29.md").read_text(encoding="utf-8").split()
    )

    assert "## 2026-06-04 — Client-facing S11 transcript (natural user help, no stale daily CLI)" in packet
    assert "Pass: S11 client-facing transcript" in packet
    assert "`/hm:wake`" in packet
    assert "`/hm:status`" in packet
    assert "`/hm:distill`" in packet
    assert "`harness-mem wake`" in packet
    assert "`harness-mem distill`" in packet

    assert "## 2026-06-04 — Client-facing S7 transcript (project mismatch clarification)" in packet
    assert "Pass: S7 client-facing transcript" in packet
    assert "`harness-mem`" in packet
    assert "`unity-side-job`" in packet
    assert "只问一次澄清" in packet

    assert "`S7 project mismatch` 与 `S11 stale-CLI help surface`" in roadmap_status
    assert "仍未完成的是 `S4`" in roadmap_status

    assert "补上了 `S7` 与 `S11` 的真实 client-facing transcript" in roadmap_v29
