from pathlib import Path


def test_roadmap_status_short_summary_mentions_v29_release_train() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert "路线已经按一个版本一个文档重切并连续收口到 v2.9" in roadmap_status
    assert (
        "PRD sync / maintenance / triage / truth-sync release train 都已落地。"
        in roadmap_status
    )
    assert "路线已经按一个版本一个文档重切并完成到 v2.8" not in roadmap_status
