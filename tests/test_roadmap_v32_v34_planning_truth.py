from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v32_v33_are_implemented_and_v34_started_with_cost_observer() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    roadmap_v32 = (REPO_ROOT / "docs" / "roadmap-v32.md").read_text(encoding="utf-8")
    roadmap_v33 = (REPO_ROOT / "docs" / "roadmap-v33.md").read_text(encoding="utf-8")
    roadmap_v34 = (REPO_ROOT / "docs" / "roadmap-v34.md").read_text(encoding="utf-8")

    assert "roadmap-v32.md" in docs_readme
    assert "roadmap-v33.md" in docs_readme
    assert "roadmap-v34.md" in docs_readme
    assert "Generated Knowledge Compiler + Basic Freshness" in docs_readme
    assert "Temporal Query and Supersede Explainability" in docs_readme
    assert "Runtime Health, Cost Discipline, and Regression Gates" in docs_readme

    assert "| v3.3.x | 已发布：Temporal Query and Supersede Explainability |" in roadmap_status
    assert "| v3.4.4 | 已发布：Cost Budget Policy |" in roadmap_status
    assert "| v3.8.0 | 当前版本：True Hybrid Retrieval Shootout |" in roadmap_status
    assert "| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates |" in roadmap_status
    assert "regression gates、true-hybrid shootout summary 和 public-claim readiness" in roadmap_status
    assert "当前 token/cost saving 仍未 ready；true-hybrid latency / retrieval recall 只限本地 synthetic / smoke artifact" in roadmap_status
    assert "| v3.2.0 | 已发布：Generated Knowledge Compiler + Basic Freshness |" in roadmap_status
    assert "| v3.2.x | 已发布：Generated Knowledge Compiler + Basic Freshness |" in roadmap_status
    assert "| v3.3.0 | 已发布：Temporal Query and Supersede Explainability |" in roadmap_status
    assert "| v3.3.1 | 已发布：Release CI dependency fix |" in roadmap_status
    assert "| v3.3.2 | 已发布：Cross-platform CI compatibility |" in roadmap_status
    assert "| v3.3.3 | 当前版本 |" not in roadmap_status
    assert "| v3.3.x | 已发布：Temporal Query and Supersede Explainability |" in roadmap_status
    assert "| v3.2.x | Generated Knowledge Compiler + Basic Freshness" in roadmap_status
    assert "| v3.3.x | 已发布：Temporal Query and Supersede Explainability" in roadmap_status
    assert "| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates" in roadmap_status
    assert "Temporal Query and Supersede Explainability" in roadmap_status
    assert "token budget、runtime health report、benchmark regression、version drift" in roadmap_status

    assert "> 状态：已发布，当前版本 3.2.0。" in roadmap_v32
    assert "### 当前实现（2026-06-07）" in roadmap_v32
    assert "citation validation" in roadmap_status
    assert "> 状态：已发布，当前版本 3.3.3。" in roadmap_v33
    assert "### 当前实现（2026-06-07）" in roadmap_v33
    assert "> 状态：已发布，当前版本 3.4.4。" in roadmap_v34
    assert "## v3.4.0：MCP Surface Cost Observer" in roadmap_v34
    assert "### 当前实现（2026-06-08）" in roadmap_v34
    assert "## v3.4.4：Cost Budget Policy" in roadmap_v34
    assert "tracked `release-snapshot.json`" in roadmap_v34
    assert "7 accepted、0 failed、0 unknown" in roadmap_v34
    assert "benchmark gate passed" in roadmap_v34
    assert '`benchmark_matrix_report()["claim_readiness"]`' in roadmap_v34
    assert "token/cost saving 与 true vector-hybrid latency 都是 `ready=false`" in roadmap_v34
    assert "generated wiki / compact page 不是 truth" in roadmap_v32
    assert "不把 `reference-projects.md` maintainer 总表当 v3.2 产品切片" in roadmap_v32
    assert "不让 AI 自动改写 confirmed truth" in roadmap_v33
    assert "完整多跳图不是必要功能" in roadmap_v33
    assert "Runtime Health, Cost Discipline, and Regression Gates" in roadmap_v34
    assert "不把 observability 做成默认后台 daemon" in roadmap_v34
    assert "不把 cost 当作 observability 子项" in roadmap_v34
    assert "不重新实现 v3.2 的 source-map freshness" in roadmap_v34
