from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _doc(name: str) -> str:
    return (REPO_ROOT / "docs" / name).read_text(encoding="utf-8")


def test_v40_docs_are_indexed_with_index_fabric_scope() -> None:
    roadmap_status = _doc("roadmap-status.md")
    docs_readme = _doc("README.md")

    assert (
        "| `roadmap-v40.md` | v4.0：Storage v2 + Rust Core + Local Memory Index Fabric 总纲 |"
        in docs_readme
    )
    assert (
        "| v4.0.0 | 已完成：Baseline, Benchmark, and Migration Contract |"
        in roadmap_status
    )
    assert (
        "| v4.0.x | 已完成：Storage v2 + Rust Core + Local Memory Index Fabric"
        in roadmap_status
    )
    assert "| v4.1.0 | 已完成：Context Sufficiency + Task-Aware Wake |" in roadmap_status
    assert "| v4.2.x | 已完成：Memory Eval Matrix + Retrieval Quality Pack |" in roadmap_status
    assert "| v4.3.0 | 已完成：Code-Memory Federation |" in roadmap_status
    assert "| v4.4.0 | 已完成：Claim Promotion Pack |" in roadmap_status
    assert "| v4.5.0 | 已完成：Release Evidence Pack |" in roadmap_status
    assert "| v5.1 | 已完成：Canonical SQLite Default Truth Runtime |" in roadmap_status
    assert "| v5.2.0 | 已完成：Default Kernel Cutover（SearchBackend Mainline） |" in roadmap_status
    assert "| v5.6.0 | 当前版本：Multi-client Release Confidence |" in roadmap_status
    assert "v4.0.1+ 未开始" not in roadmap_status
    assert "context sufficiency / task-aware wake" in roadmap_status
    assert "docs/roadmap-v40.md" in roadmap_status


def test_v40_scope_separates_storage_index_fabric_from_agentic_rag() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "Storage v2 + Rust Core + Local Memory Index Fabric" in roadmap
    assert "v4.0 只打存储、索引、热路径和 benchmark 地基" in roadmap
    assert "local-first agentic memory runtime with auditable evidence" in roadmap
    assert "| v4.1 | Context Sufficiency + Task-Aware Wake |" in roadmap
    assert "| v4.2 | Memory Evals + Retrieval Quality Pack |" in roadmap
    assert "| v4.3 | Code-Memory Federation |" in roadmap
    assert "| v4.4 | Claim Promotion Pack |" in roadmap
    assert "| v4.5 | Release Evidence Pack |" in roadmap
    assert "| v4.6-v5.0 | Evidence Hardening Track |" in roadmap
    assert "| v5.1-v5.2 | Default Kernel Cutover |" in roadmap
    assert "默认 Planning Agent / SCA loop" in roadmap
    assert "v4.1 收口 context" in roadmap
    assert "不是把 harness-mem 变成本地通用 Agent 平台" in roadmap


def test_v40_codedb_mcp_index_fabric_lessons_are_explicit() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "`codedb-mcp` 的真正价值" in roadmap
    assert "generation sidecars" in roadmap
    assert "manifest-last commits" in roadmap
    assert "compact binary sidecars" in roadmap
    assert "lazy exact / word / trigram / vector / graph indexes" in roadmap
    assert "warm process fast path" in roadmap
    assert "半写入 generation 不可见" in roadmap
    assert "`IndexManifest`" in roadmap
    assert "source fingerprint drift" in roadmap


def test_v40_benchmark_and_regression_gates_are_first_class() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "## Benchmark Gates" in roadmap
    assert "benchmark_id" in roadmap
    assert "dataset_id / dataset_hash" in roadmap
    assert "cold_start / first_lazy_load / warm_run distinction" in roadmap
    assert "claim_readiness" in roadmap
    assert "没有 artifact，就不能把收益写进 README 或 release note" in roadmap
    assert "测试通过不是 benchmark" in roadmap
    assert "Roadmap truth tests" in roadmap
    assert "manifest-last commit" in roadmap
    assert "Regression rule" in roadmap


def test_v400_current_implementation_is_contract_only() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "> 状态：v4.0.0-v4.0.5、v4.1.x、v4.2.x、v4.3.0、v4.4、v4.5、v4.6-v5.0 与 v5.1-v5.2 已完成。" in roadmap
    assert "## v5.1-v5.2：Default Kernel Cutover" in roadmap
    assert "### 当前实现（2026-06-12）" in roadmap
    assert "`harness_mem/storage/store_v2_migration.py`" in roadmap
    assert "`harness-mem maintenance migrate-store-v2 --dry-run`" in roadmap
    assert "`--profile 10k|100k|1m`" in roadmap
    assert "2026-06-12-storage-v2-baseline-smoke-v400" in roadmap
    assert "不把 canonical SQLite 设为默认 truth store" in roadmap
    assert "不引入 Rust core" in roadmap
    assert "不实现 runtime SearchBackend" in roadmap
    assert "v4.0.1 已完成 canonical store 的第一版 runtime contract" in roadmap
    assert "v4.0.2 已完成 Rust Core MVP 的发布形态地基" in roadmap
    assert "v4.0.3 已完成 Local Memory Index Fabric 和 SearchBackend contract" in roadmap
    assert "v4.0.4 已完成 lifecycle tiering 的 read-path 和 candidate contract" in roadmap
    assert "v4.0.5 已完成 distribution gate 的诊断与文档地基" in roadmap
    assert "v4.1.0 已完成 Context Sufficiency + Task-Aware Wake" in roadmap
    assert "v4.2.x 已完成 release-gated contract surface" in roadmap
    assert "v4.3.0 已完成第一版 code-memory federation contract" in roadmap
    assert "v4.4 已完成第一版 claim-promotion contract" in roadmap
    assert "v4.5 已完成第一版 release-evidence contract" in roadmap
    assert "### 当前实现（2026-06-16）" in roadmap
    assert "31 个" in roadmap


def test_v41_memory_quality_gates_are_local_and_auditable() -> None:
    roadmap = _doc("roadmap-v40.md")

    for term in [
        "context_sufficiency",
        "support_level",
        "safe_to_answer",
        "recommended_action",
        "wake_packet",
        "hard_include",
        "soft_include",
        "evict_first",
        "`CorpusProfile`",
        "`RetrievalPlan`",
        "`MetadataFilter`",
        "`SufficiencyReport`",
        "`IterativeRetrievalTrace`",
        "`ContextPlan`",
    ]:
        assert term in roadmap

    assert "cheap query classifier" in roadmap
    assert "covered" in roadmap
    assert "missing" in roadmap
    assert "conflicting" in roadmap
    assert "本地 Gemini Enterprise" in roadmap
    assert "本地 Vertex AI" in roadmap
    assert "无云、无默认 daemon" in roadmap


def test_v42_memory_evals_are_release_gates_not_latency_only() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "## v4.2：Memory Evals + Retrieval Quality Pack" in roadmap
    assert "memory evals 从维护工具升级成 release gate" in roadmap
    assert "memory runtime 是否真的" in roadmap
    for term in [
        "cross_session_resume",
        "stale_truth_rejection",
        "raw_evidence_recovery",
        "candidate_noise_rejection",
        "task_aware_wake_precision",
        "multi_client_consistency",
        "wire_format_backward_compat",
        "context_sufficiency_accuracy",
    ]:
        assert term in roadmap


def test_v40_truth_mutation_boundary_stays_hard() -> None:
    roadmap = _doc("roadmap-v40.md")

    assert "confirmed truth 变更仍必须走 candidate / review / supersede / ledger" in roadmap
    assert "AI 自治删除 confirmed truth" in roadmap
    assert "违反 candidate / review / supersede / ledger" in roadmap
    assert "generated layer 不是 truth store" in roadmap
    assert "graph sidecar does not mutate truth" in roadmap
