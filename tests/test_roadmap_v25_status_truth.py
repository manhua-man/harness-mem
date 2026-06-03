from pathlib import Path


def test_roadmap_v25_no_longer_claims_in_progress_or_pending_release() -> None:
    roadmap_v25 = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v25.md").read_text(
        encoding="utf-8"
    )

    assert "> 状态：v2.5.0 / v2.5.1 / v2.5.2 已完成。" in roadmap_v25
    assert "待版本收口 / 发版" not in roadmap_v25
    assert "> 状态：进行中。" not in roadmap_v25
