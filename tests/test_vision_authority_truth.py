from pathlib import Path


def test_vision_and_reference_docs_now_point_to_current_truth_sources() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    vision_doc = (docs_root / "roadmap-vision-v16-v18.md").read_text(encoding="utf-8")
    reference_doc = (docs_root / "reference-projects.md").read_text(encoding="utf-8")
    docs_readme = (docs_root / "README.md").read_text(encoding="utf-8")

    assert "历史远景文档（vision archive）" in vision_doc
    assert "当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。" in vision_doc
    assert "每个版本的落地形态会在前一版本收尾时再细化。" not in vision_doc

    assert "当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。" in reference_doc
    assert "路线图承诺仍以 `roadmap-v15x.md`、`roadmap-v16x.md` 和 `roadmap-vision-v16-v18.md` 为准。" not in reference_doc
    assert "历史路线设计" in reference_doc
    assert "## 证据化当前评估与参考锚点" in reference_doc
    assert "maintainer decision artifact" in reference_doc
    assert "本文不再维护跨项目总分榜" in reference_doc
    assert "### 评分规则" in reference_doc
    assert "### v4.5.0 证据分析" in reference_doc
    assert "能力维度" in reference_doc
    assert "证据分" in reference_doc
    assert "Memory runtime / wake / search" in reference_doc
    assert "用户负担与入口闭环" in reference_doc
    assert "Cost discipline | 7.4" in reference_doc
    assert "Storage v2 / canonical runtime foundation | 7.6" in reference_doc
    assert "Context sufficiency / task-aware wake | 7.5" in reference_doc
    assert "Memory eval / retrieval quality gates | 7.5" in reference_doc
    assert "Code-memory federation | 7.4" in reference_doc
    assert "Claim promotion governance | 7.8" in reference_doc
    assert "Release evidence packaging | 7.8" in reference_doc
    assert "### 参考项目锚点，不做排行榜" in reference_doc
    assert "### 快照更新规则" in reference_doc
    assert "证据变差时要降分" in reference_doc
    assert "### 硬指标 Claim Gate" in reference_doc
    assert "claim_readiness.token_cost_saving.ready" in reference_doc
    assert "claim_readiness.true_vector_hybrid_latency.ready" in reference_doc
    assert "claim_promotion_gate.policy_enforced" in reference_doc
    assert "release_evidence_pack.passed" in reference_doc
    assert "不能说 token/cost saving 已被证明" in reference_doc
    assert "token-visible paired run 的 saving delta 为负" in reference_doc
    assert "只能说本地 synthetic true-hybrid probe 无 fallback" in reference_doc
    assert "不能外推生产延迟" in reference_doc
    assert "只能说本地 smoke source-hit recall" in reference_doc
    assert "不能外推端到端回答正确率" in reference_doc
    assert "Cost discipline 和 Performance 分开评估" in reference_doc
    assert "token 降 43.1%" in reference_doc
    assert "当前 release snapshot 里的 v3.8" in reference_doc
    assert "### 主观 Scorecard" not in reference_doc
    assert "整体成熟度（主观，加权）" not in reference_doc
    assert "harness-mem v3.8 current ████████▋   8.6" not in reference_doc
    assert "当前 maintainer 评分基线" not in reference_doc
    assert "## 新增镜像项目快速深读（2026-06-08）" in reference_doc
    assert "下面这些项目已经下载到本地 `../../upstreams/`" in reference_doc
    for project_name in [
        "`OpenSpace`",
        "`Memento-Skills`",
        "`llm_wiki`",
        "`meta-kb`",
        "`hypatia`",
        "`EverOS`",
        "`hindsight`",
        "`MemChinesePalace`",
    ]:
        assert project_name in reference_doc
    assert "待镜像后再深读" not in reference_doc
    assert "目前尚未下载到本地" not in reference_doc
    assert "如果 v3.1 Auto Dream Memory Maintenance 进入实现" not in reference_doc
    assert "当前 BENCH-001 token unavailable" not in reference_doc
    assert "当前 BENCH-004 hybrid fallback 到 FTS" not in reference_doc

    assert "roadmap-vision-v16-v18.md" in docs_readme
    assert "历史远景" in docs_readme
