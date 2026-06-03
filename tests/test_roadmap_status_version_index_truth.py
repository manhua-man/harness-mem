from pathlib import Path


def test_roadmap_status_version_index_covers_v15_through_v29() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert "## 版本索引" in roadmap_status
    assert "## 后续 Roadmap" not in roadmap_status
    assert "| v1.5.x | Retrieval baseline + ingest/onboarding 基础：" in roadmap_status
    assert "| v1.6.x | Persistent vectors + memory typing + bucket budget：" in roadmap_status
    assert "| v1.7.x | Temporal truth + supersede + bounded relation graph：" in roadmap_status
    assert "| v1.8.x | Procedural memory 保守闭环：" in roadmap_status
    assert "| v2.0.x | Heuristic distill 移除：" in roadmap_status
    assert "| v2.1.x | Maintenance-only CLI + Slash/Skill/Agent workflow 重写：" in roadmap_status
    assert "| v2.2.x | AI IDE 入口闭环：" in roadmap_status
