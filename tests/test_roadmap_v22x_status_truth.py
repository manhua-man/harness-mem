from pathlib import Path


def test_roadmap_v22x_no_longer_claims_planning_status() -> None:
    roadmap_v22x = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v22x.md").read_text(
        encoding="utf-8"
    )

    assert "> 状态：v2.2.0 已完成。" in roadmap_v22x
    assert "> 状态：规划中。" not in roadmap_v22x
