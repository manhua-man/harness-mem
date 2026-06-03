from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_generic_mcp_empty_evidence_packet() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Generic MCP empty evidence packet" in packet
    assert "harness-mem version: 2.9.57" in packet
    assert "Project: `v2957-empty-packet`" in packet
    assert "Pass: S6 (empty evidence packet via raw `prepare_session_distill`)" in packet
    assert '`ingest.reason = "run_ingest=false"`' in packet
    assert "`observation_count = 0`" in packet
    assert "`observations = []`" in packet
    assert "generic MCP 的空 evidence packet 场景" in packet
