from pathlib import Path


def test_roadmap_v22x_no_longer_claims_planning_status() -> None:
    roadmap_v22x = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v22x.md").read_text(
        encoding="utf-8"
    )

    assert "> 状态：v2.2 runtime / contract 已完成；`docs/v2-user-test-packet.md` 已补 1 条" in roadmap_v22x
    assert "full cross-client release gate 仍未闭环" in roadmap_v22x
    assert "> 状态：规划中。" not in roadmap_v22x
