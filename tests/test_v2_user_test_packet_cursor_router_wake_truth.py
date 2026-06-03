from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_cursor_router_wake_transcript_boundary() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_status = " ".join(
        (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8").split()
    )
    roadmap_v29 = " ".join(
        (REPO_ROOT / "docs" / "roadmap-v29.md").read_text(encoding="utf-8").split()
    )

    assert "## 2026-06-04 — Cursor / user-mcp-router wake packet transcript" in packet
    assert "Clients: Cursor-side frontend via `user-mcp-router`" in packet
    assert "`wake(project_name=\"harness-mem\", no_auto_ingest=true)`" in packet
    assert "[...truncated]" in packet
    assert "# Memory Entries" in packet
    assert "# Essential Truth  (L1 · confirmed current)" in packet
    assert "workspace path 一起带出来" in packet

    assert "真实 `Cursor / user-mcp-router` wake transcript" in roadmap_status
    assert "不自带工作区路径" in roadmap_status
    assert "workspace provenance" in roadmap_status
    assert "`harness_mem/integration` Cursor packet run log" in roadmap_status

    assert "real Cursor / router wake transcript" in roadmap_v29
    assert "old `# Memory Entries / # Confirmed Rules` shape" in roadmap_v29
