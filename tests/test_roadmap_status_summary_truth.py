from pathlib import Path


def test_roadmap_status_short_summary_mentions_full_completed_range() -> None:
    roadmap_status = (
        Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md"
    ).read_text(encoding="utf-8")

    assert (
        "从 v1.5 baseline 到 v5.8.0 Guided Maintenance Profiles / MCP Tool Profile，"
        "主实现路线已经按一个版本一个文档重切并连续收口。"
        in roadmap_status
    )
    assert "以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release" in roadmap_status
    assert "v3.1 的默认关闭 Auto Dream / DreamRun 账本 / handle-all / undo 面、v3.2 的" in roadmap_status
    assert "source map / atomic claim / citation validation / incremental metrics、v3.3 的" in roadmap_status
    assert "current/history/as_of temporal query / supersede timeline / abstention、v3.4.x 的" in roadmap_status
    assert "MCP surface cost observer / high-output detection / `surface_cost_report` / runtime health /" in roadmap_status
    assert "benchmark matrix / version drift / cost budget policy、v3.5 的 benchmark evidence /" in roadmap_status
    assert "v4.0.1-v4.0.5 的 canonical store / Rust facade / index fabric / lifecycle /" in roadmap_status
    assert "distribution gate、v4.1.0 的 context sufficiency / task-aware wake、v4.2.x 的" in roadmap_status
    assert "memory eval matrix / retrieval quality pack、v4.3.0 的 code-memory federation、" in roadmap_status
    assert "v4.4 的 claim-promotion gate、v4.5.0 的 release-evidence pack、v5.0 的" in roadmap_status
    assert "Evidence Hardening Track、v5.1-v5.2 的 Default Kernel Cutover、v5.3-v5.6 的" in roadmap_status
    assert "v5.3-v5.6 的" in roadmap_status
    assert "Daily Flow DX / Guided Opt-in Maintenance / Outcome-Aware Context Loop /" in roadmap_status
    assert "Multi-client Release Confidence、v5.7 的 Temporal-aware Retrieval + Claims Drilldown，" in roadmap_status
    assert "以及 v5.8 的 Guided Maintenance Profiles / Generated Incremental Compile /" in roadmap_status
    assert "v3.8 已收口 benchmark evidence、generated claim hardening、skill evolution governance" in roadmap_status
    assert "未 ready 的 token/cost saving 不能写成已证明的公开节省事实" in roadmap_status
    assert "true-hybrid latency / retrieval recall 也必须限定在本地 synthetic / smoke artifact" in roadmap_status
    assert "默认 reranker/HyDE 启用、code-intel token/runtime 或端到端回答质量" in roadmap_status
    assert "v1.5 baseline、v1.6 persistent vectors" in roadmap_status
    assert "v2.2 用户入口闭环（Slash/Skill/自然语言 + Agent 背后 MCP；跨客户端能力已交付，细节见维护者测试包）" in roadmap_status
    assert "路线已经按一个版本一个文档重切并完成到 v2.8" not in roadmap_status
    assert "v2.2 已完成用户入口闭环，但当前产品仍不是后台自学习或自动随手记。" not in roadmap_status
    assert "后续只保留 artifact-backed benchmark 扩展与 dashboard 等非必要后置项。" not in roadmap_status
