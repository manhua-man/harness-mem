from pathlib import Path


def test_roadmap_status_short_summary_mentions_full_completed_range() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert "从 v1.5 baseline 到 v3.8.0 True Hybrid Retrieval Shootout，主实现路线已经按一个版本一个文档重切并连续收口。" in roadmap_status
    assert "以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release" in roadmap_status
    assert "v3.1 的默认关闭 Auto Dream / DreamRun 账本 / handle-all / undo 面、v3.2 的" in roadmap_status
    assert "source map / atomic claim / citation validation / incremental metrics、v3.3 的" in roadmap_status
    assert "current/history/as_of temporal query / supersede timeline / abstention、v3.4.x 的" in roadmap_status
    assert "MCP surface cost observer / high-output detection / `surface_cost_report` / runtime health /" in roadmap_status
    assert "benchmark matrix / version drift / cost budget policy、v3.5 的 benchmark evidence /" in roadmap_status
    assert "v3.8 已收口 benchmark evidence、generated claim hardening、skill evolution governance" in roadmap_status
    assert "未 ready 的 token/cost saving 不能写成已证明的公开节省事实" in roadmap_status
    assert "true-hybrid latency / retrieval recall 也必须限定在本地 synthetic / smoke artifact" in roadmap_status
    assert "v1.5 baseline、v1.6 persistent vectors" in roadmap_status
    assert "v2.2 用户入口闭环（Slash/Skill/自然语言 + Agent 背后 MCP；跨客户端能力已交付，细节见维护者测试包）" in roadmap_status
    assert "路线已经按一个版本一个文档重切并完成到 v2.8" not in roadmap_status
    assert "v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。" not in roadmap_status
    assert "后续只保留 artifact-backed benchmark 扩展与 dashboard 等非必要后置项。" not in roadmap_status
