from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_generic_mcp_review_only_summary() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Generic MCP distill summary stays repair-only" in packet
    assert "harness-mem version: 2.9.59" in packet
    assert "Project: `v2959-review-only`" in packet
    assert "Pass: near-neighbor S12" in packet
    assert '`next_user_action = "review the deferred candidates and mention any incorrect item id"`' in packet
    assert "did **not** contain `/hm:review`" in packet
    assert "repair-only 边界" in packet
