from pathlib import Path


def test_roadmap_status_short_summary_mentions_full_completed_range() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert "从 v1.5 baseline 到 v2.9 release train，路线已经按一个版本一个文档重切并连续收口。" in roadmap_status
    assert (
        "PRD sync / maintenance / triage / truth-sync release\ntrain 都已落地。"
        in roadmap_status
    )
    assert "v1.5 baseline、v1.6 persistent vectors" in roadmap_status
    assert "路线已经按一个版本一个文档重切并完成到 v2.8" not in roadmap_status
    assert "v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。" not in roadmap_status
