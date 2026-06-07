from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_records_hermes_oneshot_write_read_smoke() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "## 2026-06-04 — Hermes oneshot write/read smoke" in packet
    assert "Clients: Hermes CLI (`hermes -z/--oneshot`) as a real non-Claude frontend" in packet
    assert '`hermes -z "reply with the single word ok" --yolo` returned `ok`' in packet
    assert 'explicit Hermes wake prompt using `wake(project_name="harness-mem", no_auto_ingest=true)` returned `PASS`' in packet
    assert "returned the exact wake line for" in packet
    assert "Hermes cross-client sentinel fact." in packet
    assert 'cmd_wake_up("harness-mem", no_auto_ingest=true)' in packet
    assert "当前 `claude -p` 在这台机器上仍然会卡住" in packet
