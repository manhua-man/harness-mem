from pathlib import Path


def test_roadmap_v29_header_describes_release_train() -> None:
    roadmap_v29 = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v29.md").read_text(
        encoding="utf-8"
    )

    assert "主题：PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train。" in roadmap_v29
    assert "主题：PRD Sync Candidate Surface。" not in roadmap_v29


def test_roadmap_v29_goal_mentions_v29_expanded_beyond_prd_sync() -> None:
    roadmap_v29 = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v29.md").read_text(
        encoding="utf-8"
    )

    assert "也就是说，`v2.9` 已不再只是 “PRD sync candidate surface” 这一条单独切片" in roadmap_v29
    assert "后续 v2.9.1+ 的版本线则沿着同一条思路继续推进：" in roadmap_v29
    assert "- 把 `/hm:status`、plugin doctor helper 等高可见维护/分诊入口收成正式 surface" in roadmap_v29
