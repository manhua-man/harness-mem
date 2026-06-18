from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v57_docs_are_planned_and_indexed() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    roadmap_v57 = (REPO_ROOT / "docs" / "roadmap-v57.md").read_text(encoding="utf-8")

    assert "roadmap-v57.md" in docs_readme
    assert "Temporal-aware Retrieval + Claims Drilldown" in docs_readme
    assert "规划 v5.9-v5.12" in docs_readme
    assert "v5.7（已发布）：Temporal-aware Retrieval + Claims Drilldown" in docs_readme
    assert "| v5.7 | 已完成：Temporal-aware Retrieval + Claims Drilldown |" in roadmap_status
    assert "## 已完成：v5.7 Temporal-aware Retrieval" in roadmap_status
    assert "v5.7.0 Temporal scope on mainline | 已完成，focused gate 已补" in roadmap_status
    assert "v5.7.1 Temporal drilldown contract | 已完成，release gate 已补" in roadmap_status
    assert "v5.7.2 Generated claims drilldown | 已实现，release gate 接入" in roadmap_status
    assert "v5.7.3 Temporal product eval | gate 已接入" in roadmap_status
    assert "docs/roadmap-v57.md" in roadmap_status
    assert "| v5.8.0 | 当前版本：Guided Maintenance Profiles + Generated Incremental Compile + MCP Tool Profile |" in roadmap_status
    assert "> 状态：**已发布**（随 v5.8.0 release train 收口；基线版本 v5.6.0" in roadmap_v57
    assert "generated claim drilldown 已接线并通过 focused tests" in roadmap_v57
    assert "`temporal_product_query` artifact 支撑" in roadmap_v57
    assert "regression gate | **已接入**" in roadmap_v57
    assert "temporal_query" in roadmap_v57
    assert "wiki 产品化" in roadmap_v57
    assert "always-on daemon" in roadmap_v57
    assert "token_cost_saving.ready=false" in roadmap_v57
