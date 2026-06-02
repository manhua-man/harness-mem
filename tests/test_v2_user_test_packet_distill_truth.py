from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v2_user_test_packet_uses_auto_review_as_generic_distill_surface() -> None:
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")

    assert "顺序调 `prepare_session_distill` → `suggest_*` → `auto_review_candidates`" in packet
    assert (
        "依次调 `prepare_session_distill` → `suggest_memory_entry` / `suggest_rule` / "
        "`suggest_relation_fact` / `create_task_handoff` → `auto_review_candidates`"
        in packet
    )
    assert "→ `list_candidates` → `auto_review_candidates`" not in packet
    assert "→ `list_candidates(status=\"pending\")` → `auto_review_candidates`" not in packet
