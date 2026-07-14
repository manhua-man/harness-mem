from __future__ import annotations

from pathlib import Path


def test_public_docs_describe_hooks_as_evidence_staging_not_auto_summary() -> None:
    policy = Path("docs/autopilot-search-policy.md").read_text(encoding="utf-8")
    cold_start = Path("docs/demo-cold-start.md").read_text(encoding="utf-8")
    flow_diagram = Path("docs/assets/harness-mem-cold-start-flow.svg").read_text(
        encoding="utf-8"
    )

    assert "sync evidence + queue a distill task" in policy
    assert "next Agent-capable wake or /hm:distill" in policy
    assert "hooks only sync transcript evidence and queue distill work" in cold_start
    assert "Hooks sync evidence and queue work" in flow_diagram
    assert "post-turn-maintenance runs distill" not in flow_diagram


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
    assert "auto/user confirmed truth" in diagram
    assert "current package version 0.8.9" not in diagram
