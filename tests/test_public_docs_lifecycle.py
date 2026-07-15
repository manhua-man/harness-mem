from __future__ import annotations

from pathlib import Path


def test_public_docs_describe_hooks_as_source_snapshot_not_auto_summary() -> None:
    policy = Path("docs/autopilot-search-policy.md").read_text(encoding="utf-8")
    cold_start = Path("docs/demo-cold-start.md").read_text(encoding="utf-8")
    flow_diagram = Path("docs/assets/harness-mem-cold-start-flow.svg").read_text(
        encoding="utf-8"
    )

    assert "snapshot an immutable source revision + queue all chunks" in policy
    assert "next Agent-capable wake or /hm:distill" in policy
    assert "hooks only capture an immutable native transcript source revision" in cold_start
    assert "Hooks save immutable revisions and queue every chunk" in flow_diagram
    assert "sync evidence + queue a distill task" not in policy
    assert "hooks only sync transcript evidence" not in cold_start
    assert "post-turn-maintenance runs distill" not in flow_diagram


def test_legacy_lifecycle_docs_use_lossless_session_distill_contract() -> None:
    docs = {
        path: Path(path).read_text(encoding="utf-8")
        for path in (
            "docs/autopilot-search-policy.md",
            "docs/demo-cold-start.md",
            "docs/auto-promoted-memory-governance.md",
            "docs/memory-adoption.md",
        )
    }
    combined = "\n".join(docs.values())

    assert "wake -> search -> distill -> review -> dream" in combined
    assert "immutable source revision" in combined
    assert "without truncation" in combined
    assert "checkpoint each chunk" in combined
    assert "final-session review" in combined
    assert "idempotent candidates" in combined
    assert "finalize_session_distill" in combined
    assert "auto-review + Dream" in combined

    assert "evidence packet" not in combined.lower()
    assert "packet + Packet Audit" not in combined
    assert "Prepare an evidence packet from project-scoped observations" not in combined


def test_public_docs_require_complete_lossless_distill_before_promotion() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    chinese = Path("README.zh-CN.md").read_text(encoding="utf-8")
    flow = Path("docs/assets/harness-mem-lossless-session-flow.svg").read_text(
        encoding="utf-8"
    )

    assert "without truncating them" in readme
    assert "finalize_session_distill" in readme
    assert "不截断内容" in chinese
    assert "zero character loss" in flow
    assert "every expected chunk is checkpointed" in flow


def test_chinese_readme_does_not_send_normal_users_to_the_hook_installer() -> None:
    readme = Path("README.zh-CN.md").read_text(encoding="utf-8")

    assert "不需要用户运行 hook installer" in readme
    assert "harness-mem integration install-hook-suite --client cursor" not in readme


def test_runtime_diagram_matches_current_storage_and_truth_contract() -> None:
    diagram = Path("docs/assets/harness-mem-runtime-layered-architecture.svg").read_text(
        encoding="utf-8"
    )

    assert 'viewBox="0 0 1510 1000"' in diagram
    assert "canonical SQLite / profiles" in diagram
    assert "raw revisions / chunks" in diagram
    assert "auto/user confirmed truth" in diagram
    assert "current package version 0.8.9" not in diagram


def test_distill_agent_surfaces_use_lossless_finalize_contract() -> None:
    skill = Path("tools/session-distill/SKILL.md").read_text(encoding="utf-8")
    command = Path("plugins/harness-mem/commands/hm/daily/distill.md").read_text(
        encoding="utf-8"
    )
    plugin_skill = Path("plugins/harness-mem/skills/harness-mem/SKILL.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join((skill, command, plugin_skill))

    assert "submit_distill_chunk" in combined
    assert "finalize_session_distill" in combined
    assert "distill_job_id" in command
    assert "observation_limit=5" not in combined
    assert "max_chars_per_observation=6000" not in combined
    assert "auto_review_candidates(project_name=<project>, apply=True)" not in combined
    assert "auto_review_candidates` is the final `/hm:distill` stage" not in combined


def test_repo_local_duplicate_distill_runtime_is_removed() -> None:
    skill = Path("tools/session-distill/SKILL.md").read_text(encoding="utf-8")
    sync_policy = Path("tools/session-distill/SYNC_POLICY.md").read_text(
        encoding="utf-8"
    )

    assert not Path("tools/session-distill/lib").exists()
    assert not Path("tools/session-distill/bin").exists()
    assert "不包含独立 CLI" in skill
    assert "contains no executable runtime" in sync_policy
