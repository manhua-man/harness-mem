from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_cursor_router_wake_transcript_boundary() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    roadmap_v29 = " ".join(
        (REPO_ROOT / "docs" / "roadmap-v29.md").read_text(encoding="utf-8").split()
    )

    assert "## 2026-06-04 — Cursor / user-mcp-router wake packet transcript" in packet
    assert "Clients: Cursor-side frontend via `user-mcp-router`" in packet
    assert "`wake(project_name=\"harness-mem\", no_auto_ingest=true)`" in packet
    assert "an earlier Cursor / router wake run existed" in packet
    assert "[...truncated]" in packet
    assert "# Essential Truth  (L1 · confirmed current)" in packet
    assert "`wake_sections`" in packet
    assert "`essential_truth`" in packet
    assert "serverInfo.version = \"2.9.61\"" in packet

    assert "real Cursor / router wake transcript" in roadmap_v29
    assert "routed wake now returns `wake_sections` / `essential_truth`" in roadmap_v29
