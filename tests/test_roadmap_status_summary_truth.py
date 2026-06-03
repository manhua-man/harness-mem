from pathlib import Path


def test_roadmap_status_short_summary_mentions_full_completed_range() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert "从 v1.5 baseline 到 v2.9 release train，主实现路线已经按一个版本一个文档重切并连续收口。" in roadmap_status
    assert "以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release" in roadmap_status
    assert "train 都已落地。" in roadmap_status
    assert "v1.5 baseline、v1.6 persistent vectors" in roadmap_status
    assert "v2.2 用户入口闭环（runtime / contract 已落地，且已有 Codex + generic MCP 两条 non-Claude smoke entry，Cursor hook install 已验证，但手工 full matrix gate 未闭）" in roadmap_status
    assert "路线已经按一个版本一个文档重切并完成到 v2.8" not in roadmap_status
    assert "v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。" not in roadmap_status
