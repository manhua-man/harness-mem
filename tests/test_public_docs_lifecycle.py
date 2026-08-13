from __future__ import annotations

import re
from pathlib import Path

from harness_mem.plugin_assets import DAILY_COMMANDS


def _invocation_action_set(path: str, heading: str) -> set[str]:
    content = Path(path).read_text(encoding="utf-8")
    block = content.split(heading, 1)[1].split('<p align="center">', 1)[0]
    command_line = next(line for line in block.splitlines() if line.startswith("- `/hm:*`"))
    values = set(re.findall(r"`([^`]+)`", command_line))
    values.discard("/hm:*")
    return values


def _plugin_host_action_set(row: str, prefix: str) -> set[str]:
    return set(re.findall(re.escape(prefix) + r"([a-z-]+)", row))


def test_public_invocation_docs_match_the_daily_action_contract() -> None:
    expected = set(DAILY_COMMANDS)
    assert _invocation_action_set("README.md", "Invocation surfaces") == expected
    assert _invocation_action_set("README.zh-CN.md", "触发入口") == expected

    plugin = Path("plugins/harness-mem/README.md").read_text(encoding="utf-8")
    claude_row = next(line for line in plugin.splitlines() if line.startswith("| Claude Code |"))
    codex_row = next(line for line in plugin.splitlines() if line.startswith("| Codex |"))
    other_row = next(
        line
        for line in plugin.splitlines()
        if line.startswith("| Cursor, Grok, Hermes, OpenCode, Antigravity |")
    )
    assert _plugin_host_action_set(claude_row, "/hm:") == expected
    assert _plugin_host_action_set(codex_row, "$hm-") == expected
    assert _plugin_host_action_set(other_row, "/hm-") == expected


def test_doctor_does_not_publish_retired_weak_link_experiment() -> None:
    doctor = Path("harness_mem/commands/doctor.py").read_text(encoding="utf-8")
    assert "Weak-link signal influence" not in doctor
    assert "experimental skills" not in doctor
    assert "set weak_link_signals=true" not in doctor


def test_retired_terminal_daily_command_modules_are_removed() -> None:
    retired = (
        "candidates.py",
        "handoff.py",
        "profile.py",
        "search.py",
        "status.py",
    )
    for name in retired:
        assert not (Path("harness_mem/commands") / name).exists()


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


def test_current_canvases_match_0910_automation_and_live_status_contract() -> None:
    catalog = Path("canvases/README.md").read_text(encoding="utf-8")
    how_it_works = Path(
        "canvases/harness-mem-how-it-works-0-9-10.canvas.tsx"
    ).read_text(encoding="utf-8")
    readiness = Path(
        "canvases/harness-mem-readiness-0-9-10.canvas.tsx"
    ).read_text(encoding="utf-8")

    assert "harness-mem-how-it-works-0-9-10.canvas.tsx" in catalog
    assert "harness-mem-readiness-0-9-10.canvas.tsx" in catalog
    assert "7 Daily actions" in how_it_works
    assert "27 public MCP tools" in how_it_works
    assert "promoted / no_candidate" in how_it_works
    assert "review 是用户主动审计与纠错支路" in how_it_works
    assert "suggest_*" not in how_it_works
    assert "reflection_once" not in how_it_works
    assert "worker.mode" not in how_it_works
    assert 'const RELEASE_VERSION = "0.9.10"' in readiness
    assert 'const RUNNING_MCP_VERSION = "0.9.9.1"' in readiness
    assert "Release maturity" in readiness
    assert "Live operations" in readiness
    assert "BACKLOG_PARKED = 198" in readiness
    assert "不提供一个掩盖运营问题的综合分" in readiness


def test_distill_agent_surfaces_use_lossless_finalize_contract() -> None:
    skill = Path("tools/hm-distill/SKILL.md").read_text(encoding="utf-8")
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
    assert "session_summary" in combined
    legacy_tool_path = str(Path("tools") / ("session" + "-distill")).replace("\\", "/")
    assert legacy_tool_path not in combined


def test_repo_local_duplicate_distill_runtime_is_removed() -> None:
    skill = Path("tools/hm-distill/SKILL.md").read_text(encoding="utf-8")

    assert not Path("tools/hm-distill/lib").exists()
    assert not Path("tools/hm-distill/bin").exists()
    assert not (Path("tools") / ("session" + "-distill")).exists()
    assert not Path("tools/hm-distill/SYNC_POLICY.md").exists()
    assert not Path("tools/hm-distill/UPSTREAM_ALIGNMENT.md").exists()
    assert "name: hm-distill" in skill
    assert "Use one public flow" in skill


def test_hm_distill_keeps_one_public_flow_with_optional_internal_helpers() -> None:
    skill = Path("tools/hm-distill/SKILL.md").read_text(encoding="utf-8").lower()
    retired_terms = (
        "draft claim",
        "smart-search",
        "trellis",
    )
    optional_skill_dirs = (
        "grill-before-distill",
        "answer-memory-evidence",
        "ask-memory-boundary",
    )

    assert "candidate admission" in skill
    assert "only runtime-derived `answered`" in skill
    assert "conditional collaborator routing" in skill
    assert "do not wait for the user to invoke them" in skill
    assert "do not load all three pre-emptively" in skill
    assert "formal `answer_packet`" in skill
    assert not any(term in skill for term in retired_terms)
    for name in optional_skill_dirs:
        helper = Path("plugins/harness-mem/skills") / name / "SKILL.md"
        assert helper.is_file()
        assert "do not wait for explicit user invocation" in helper.read_text(
            encoding="utf-8"
        ).lower()


def test_active_docs_do_not_restore_legacy_distill_product_name() -> None:
    legacy_name = "session" + "-distill"
    paths = [
        Path("README.md"),
        Path("README.zh-CN.md"),
        Path("CHANGELOG.md"),
        *Path("docs").rglob("*.md"),
        *Path("tools/hm-distill").rglob("*.md"),
        *Path("plugins/harness-mem").rglob("*.md"),
        *Path("canvases").rglob("*.tsx"),
    ]

    for path in paths:
        assert legacy_name not in path.read_text(encoding="utf-8"), path


def test_active_governance_docs_use_single_public_write_surface() -> None:
    active_paths = [
        Path("docs/auto-promoted-memory-governance.md"),
        Path("docs/roadmap.md"),
        Path("plugins/harness-mem/commands/hm/daily/distill.md"),
        Path("plugins/harness-mem/skills/harness-mem/SKILL.md"),
        Path("plugins/harness-mem/skills/harness-mem-autopilot/SKILL.md"),
        Path("plugins/harness-mem/skills/grill-with-docs/SKILL.md"),
        Path("tools/hm-distill/SKILL.md"),
        Path("tools/hm-distill/references/distillation-rules.md"),
    ]
    generated_roots = [
        Path(".agents"),
        Path(".claude"),
        Path(".cursor"),
        Path(".grok"),
        Path(".opencode"),
    ]
    generated_paths = [
        path
        for root in generated_roots
        for path in root.rglob("*.md")
    ]

    retired_names = ("suggest_", "confirm_", "reject_", "create_task_handoff")
    for path in [*active_paths, *generated_paths]:
        content = path.read_text(encoding="utf-8")
        assert not any(name in content for name in retired_names), path

    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_paths)
    assert 'govern_memory(action="suggest")' in combined
    assert 'govern_memory(action="decide")' in combined
    assert 'govern_memory(action="handoff")' in combined


def test_grill_with_docs_is_explicit_and_provenance_pinned() -> None:
    skill_root = Path("plugins/harness-mem/skills/grill-with-docs")
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
    provenance = (skill_root / "references/upstream.md").read_text(
        encoding="utf-8"
    )

    assert "Do not run this interactive flow inside wake" in skill
    assert "allow_implicit_invocation: false" in metadata
    assert "2ab958093e83e0ec752e6c1c5932da465bf23e0c" in provenance
    assert "MIT" in provenance


def test_current_roadmap_is_0_9_x_and_internal_doc_duplicates_are_removed() -> None:
    roadmap = Path("docs/roadmap.md").read_text(encoding="utf-8")
    scope_ledger = Path("docs/roadmap/defer.md").read_text(encoding="utf-8")

    assert "0.9.3" in roadmap
    assert "0.9.x" in roadmap
    assert "stays on the 0.8.x line" not in roadmap
    assert "`pyproject.toml` `0.8.N`" not in roadmap
    assert "current 0.9.x scope ledger" in scope_ledger
    assert not Path("docs/internal/roadmap.md").exists()
    assert not Path("docs/internal/memory-adoption.md").exists()
    evidence_policy = Path("docs/memory-adoption.md").read_text(encoding="utf-8")
    assert "runtime Answer Gate" in evidence_policy
    assert "Trellis" not in evidence_policy
    assert "smart-search" not in evidence_policy
    assert not Path("docs/internal/agent-memory-retrieval-research-2026.md").exists()


def test_legacy_storage_cutoff_and_delete_semantics_are_documented() -> None:
    lifecycle = Path("docs/storage-legacy-lifecycle.md").read_text(encoding="utf-8")
    compatibility = Path("docs/compatibility-inventory.md").read_text(
        encoding="utf-8"
    )
    skill = Path("plugins/harness-mem/skills/harness-mem/SKILL.md").read_text(
        encoding="utf-8"
    )

    for body in (lifecycle, compatibility):
        assert "0.9.x" in body
        assert "1.0.0" in body
        assert "2027-01-31" in body
    assert "processed-source cleanup" in skill.lower()
    assert "privacy erasure" in skill.lower()
    assert "only soft-deletes harness-mem" not in skill
