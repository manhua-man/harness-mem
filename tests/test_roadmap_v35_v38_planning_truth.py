from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _doc(name: str) -> str:
    return (REPO_ROOT / "docs" / name).read_text(encoding="utf-8")


def test_v35_v38_completed_docs_are_indexed_as_shipped_work() -> None:
    roadmap_status = _doc("roadmap-status.md")
    docs_readme = _doc("README.md")

    assert "| v3.5.x | 已完成：Benchmark Evidence and Public Claim Readiness |" in roadmap_status
    assert "| v3.6.x | 已完成：Generated Claim Hardening |" in roadmap_status
    assert "| v3.7.x | 已完成：Skill Evolution Governance |" in roadmap_status
    assert "| v3.8.x | 已完成：True Hybrid Retrieval Shootout |" in roadmap_status
    assert "| v4.1.0 | 当前版本：Context Sufficiency + Task-Aware Wake |" in roadmap_status

    for roadmap_name in [
        "roadmap-v35.md",
        "roadmap-v36.md",
        "roadmap-v37.md",
        "roadmap-v38.md",
    ]:
        assert roadmap_name in roadmap_status
        assert roadmap_name in docs_readme


def test_v35_benchmark_claim_boundaries_are_explicit() -> None:
    roadmap = _doc("roadmap-v35.md")

    assert "> 状态：已完成。" in roadmap
    assert "Benchmark Evidence and Public Claim Readiness" in roadmap
    assert "不把 `pytest pass` 当 benchmark 结果。" in roadmap
    assert "不把旧 smoke、429、partial attempt artifact 混进 accepted release snapshot。" in roadmap
    assert "不对外宣称 token/cost saving 或 true vector-hybrid latency，除非 claim gate 为 ready。" in roadmap
    assert "`claim_readiness` 覆盖 token/cost saving、true vector-hybrid latency" in roadmap


def test_v36_generated_claim_boundaries_are_explicit() -> None:
    roadmap = _doc("roadmap-v36.md")

    assert "> 状态：已完成。" in roadmap
    assert "Generated Claim Hardening" in roadmap
    assert "generated claim / wiki prose 不是 confirmed truth。" in roadmap
    assert "不让 AI 直接把 generated claim 写进 durable truth。" in roadmap
    assert "没有可验证 source 的 claim 不进 compact wake。" in roadmap
    assert "`generated_review_queue`" in roadmap
    assert "`# Trust`、`# Source IDs` 和" in roadmap


def test_v37_skill_evolution_boundaries_are_explicit() -> None:
    roadmap = _doc("roadmap-v37.md")

    assert "> 状态：已完成。" in roadmap
    assert "Skill Evolution Governance" in roadmap
    assert "不默认把 procedural skill 注入 wake。" in roadmap
    assert "不让 skill 自己改写 confirmed skill body。" in roadmap
    assert "必须显式 `search_skills`、hint 或 drilldown。" in roadmap
    assert "MCP `record_skill_result` 支持 optional `surface`、`source_ids`" in roadmap


def test_v38_true_hybrid_retrieval_boundaries_are_explicit() -> None:
    roadmap = _doc("roadmap-v38.md")

    assert "> 状态：已完成。" in roadmap
    assert "True Hybrid Retrieval Shootout" in roadmap
    assert "FTS baseline" in roadmap
    assert "vector baseline" in roadmap
    assert "hybrid retrieval" in roadmap
    assert "不在 artifact 之前宣称 true vector-hybrid latency 已证明。" in roadmap
    assert "`claim_readiness.retrieval_recall`" in roadmap
