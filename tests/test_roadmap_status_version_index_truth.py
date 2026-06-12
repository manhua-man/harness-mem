from pathlib import Path


def test_roadmap_status_version_index_covers_v15_through_v38() -> None:
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
    assert "| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates：" in roadmap_status
    assert "| v3.5.x | 已完成：Benchmark Evidence and Public Claim Readiness：" in roadmap_status
    assert "| v3.6.x | 已完成：Generated Claim Hardening：" in roadmap_status
    assert "| v3.7.x | 已完成：Skill Evolution Governance：" in roadmap_status
    assert "| v3.8.x | 已完成：True Hybrid Retrieval Shootout：" in roadmap_status
    assert "| v4.0.0 | 已完成：Baseline, Benchmark, and Migration Contract：" in roadmap_status
    assert "| v4.0.x | 已完成：Storage v2 + Rust Core + Local Memory Index Fabric：" in roadmap_status
    assert "| v4.1.0 | 已完成：Context Sufficiency + Task-Aware Wake：" in roadmap_status
    assert "| v4.2.x | 已完成：Memory Eval Matrix + Retrieval Quality Pack：" in roadmap_status
    assert "| v4.3.0 | 已完成：Code-Memory Federation：" in roadmap_status
    assert "| v4.4.0 | 已完成：Claim Promotion Pack：" in roadmap_status
    assert "| v4.5.0 | 当前版本：Release Evidence Pack：" in roadmap_status
    assert "v4.0.1+ 未开始" not in roadmap_status
