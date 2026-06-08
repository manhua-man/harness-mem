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
    assert "Reference Scorecard and Absorption Priorities" in reference_doc
    assert "maintainer decision artifact" in reference_doc
    assert "### 数值图口径" in reference_doc
    assert "整体成熟度（主观，加权）" in reference_doc
    assert "harness-mem v3.4 shipped ████████▋   8.6" in reference_doc
    assert "### 硬指标 Claim Gate" in reference_doc
    assert "claim_readiness.token_cost_saving.ready" in reference_doc
    assert "claim_readiness.true_vector_hybrid_latency.ready" in reference_doc
    assert "不能说 token/cost saving 已被证明" in reference_doc
    assert "只能说本地 synthetic true-hybrid probe 无 fallback" in reference_doc
    assert "不能外推生产延迟" in reference_doc
    assert "只能说本地 smoke source-hit recall" in reference_doc
    assert "不能外推端到端回答正确率" in reference_doc
    assert "必须单独成类，不能混进 observability" in reference_doc
    assert "token 降 43.1%" in reference_doc
    assert "`harness-mem v3.4 shipped` 代表 v3.1-v3.4 完成后的当前基线" in reference_doc
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

    assert "roadmap-vision-v16-v18.md" in docs_readme
    assert "历史远景" in docs_readme
