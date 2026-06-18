from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v58_docs_track_partial_implementation_without_overclaim() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    roadmap_v58 = (REPO_ROOT / "docs" / "roadmap-v58.md").read_text(encoding="utf-8")

    assert "roadmap-v58.md" in docs_readme
    assert "MCP `minimal\\|full` profile" in docs_readme
    assert "| v5.8.0 | 当前版本：Guided Maintenance Profiles + Generated Incremental Compile + MCP Tool Profile |" in roadmap_status
    assert "v5.8.0 Guided maintenance profiles | profile/config dry-run 已实现，regression smoke 已补" in roadmap_status
    assert "v5.8.1 Generated incremental compile | 代码已实现，focused gate 已补" in roadmap_status
    assert "v5.8.2 Maintenance regression | 已补" in roadmap_status
    assert "不新增 MCP tool" in roadmap_status
    assert "未自动运行 dream/metabolism" in roadmap_status
    assert "v5.8.3 MCP tool profile | 已完成，release gate 已补" in roadmap_status
    assert "> 状态：**已发布**（当前 package v5.8.0；基线版本 v5.6.0" in roadmap_v58
    assert "maintenance regression smoke 已补" in roadmap_v58
    assert "`tests/loop_harness/test_guided_maintenance_profiles.py`" in roadmap_v58
    assert "`ProjectProfile.maintenance_profile` 可由 `update_project_profile` 设置" in roadmap_v58
    assert "`maintenance rebuild-wiki-bridge --incremental`" in roadmap_v58
    assert "不写性能收益 claim" in roadmap_v58
