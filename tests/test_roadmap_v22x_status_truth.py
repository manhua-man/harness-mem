from pathlib import Path


def test_roadmap_v22x_no_longer_claims_planning_status() -> None:
    roadmap_v22x = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v22x.md").read_text(
        encoding="utf-8"
    )

    assert "> 状态：v2.2 runtime / contract 与 OpenSpec `5.5` 手工 release gate 已完成；" in roadmap_v22x
    assert "Claude Code entry 与 non-Claude entry" in roadmap_v22x
    assert "不再阻塞 v2.2 闭环" in roadmap_v22x
    assert "> 状态：规划中。" not in roadmap_v22x
