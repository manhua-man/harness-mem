from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_roadmap_v22x_uses_auto_review_surface() -> None:
    roadmap = (REPO_ROOT / "docs" / "roadmap-v22x.md").read_text(encoding="utf-8")

    assert (
        "`/hm:distill` 路径固定为 `prepare_session_distill -> session-distill -> "
        "suggest_* -> auto_review_candidates(apply=true) -> summary`"
        in roadmap
    )
    assert "suggest_* -> list_candidates -> auto-review/confirm/reject -> summary" not in roadmap
