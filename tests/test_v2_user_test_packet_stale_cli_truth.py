from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_stale_cli_surface_scan() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Stale CLI surface scan (repo truth, packet S11)" in packet
    assert "harness-mem version: 2.9.60" in packet
    assert 'rg "harness-mem (wake|search|timeline|candidates|distill)\\b"' in packet
    assert "`AGENTS.md`: `harness-mem distill` only appears inside a sentence that says the CLI subcommand was removed in v2.0" in packet
    assert "`tools/session-distill/SKILL.md`: `harness-mem ingest` / `harness-mem distill` only appear inside a sentence that says ordinary users are **not required** to run them manually" in packet
    assert "no hit in `README.md`" in packet
    assert "no hit in `plugins/harness-mem/README.md`" in packet
    assert "no hit in `plugins/harness-mem/commands/hm/*.md`" in packet
