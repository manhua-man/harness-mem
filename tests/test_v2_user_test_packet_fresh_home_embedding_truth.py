from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_fresh_home_embedding_enabled_smoke() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Generic MCP fresh-home write-path smoke" in packet
    assert "harness-mem version: 2.9.56" in packet
    assert "Environment: isolated temp home, embeddings enabled, empty local HF cache" in packet
    assert "suggest_memory_entry(...)` returned success in `0.357s`" in packet
    assert "is not cached locally; skipping write-path vec generation" in packet
    assert "不再需要先设 `HARNESS_MEM_DISABLE_EMBEDDINGS=1`" in packet
    assert "它**不等于** cold cache 下已经拿到了 vec row" in packet
