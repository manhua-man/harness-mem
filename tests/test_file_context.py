from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, Observation, ProjectProfile, Skill, TaskHandoff
from harness_mem.file_context import build_file_context
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


def _absolute_repo_path(relative_path: str) -> str:
    return str(Path("F:/memory-lab/harness-mem") / relative_path.replace("/", "\\"))


def _seed_profile(backend: LocalMemoryBackend, *, project_name: str, key_files: list[str]) -> ProjectProfile:
    profile = ProjectProfile(
        project_name=project_name,
        description="File context test project",
        stacks=["python", "sqlite"],
        key_files=key_files,
    )
    run(LocalProjectProfileStore(backend.data_dir).save(profile))
    return profile


def test_build_file_context_returns_explicit_empty_result_for_blank_path(
    backend: LocalMemoryBackend,
) -> None:
    result = run(build_file_context(backend, project_name=None, path="   "))

    assert result.path_provided is False
    assert result.items == []
    assert result.notice == "no path provided"
    assert result.cost_hint.estimated_tokens == 0
    assert result.cost_hint.disclosure_level == "L0"
    assert result.stale_file_signal.state == "none"


def test_build_file_context_surfaces_associated_items_and_cost(
    backend: LocalMemoryBackend,
) -> None:
    project_name = "file-context-project"
    relative_path = "harness_mem/mcp/server.py"
    query_path = _absolute_repo_path(relative_path)
    now = datetime.now(timezone.utc)

    profile = _seed_profile(backend, project_name=project_name, key_files=[relative_path])
    observation = Observation(
        session_id="file-context-session",
        client="codex",
        raw_content=(
            "Edited harness_mem/mcp/server.py to register the new file_context tool "
            "without leaking stdout."
        ),
        content_type="transcript",
        metadata={"project_name": project_name},
    )
    run(backend.verbatim_store.save(observation))

    current_entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="harness_mem/mcp/server.py owns MCP tool registration.",
        source="manual",
        confidence=0.95,
    )
    run(backend.structured_store.save_memory_entry(current_entry))
    historical_entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="harness_mem/mcp/server.py used to own the legacy MCP tool registration flow.",
        source="manual",
        confidence=0.8,
        valid_to=now - timedelta(days=2),
    )
    run(backend.structured_store.save_memory_entry(historical_entry))

    rule = ConfirmedRule(
        project_name=project_name,
        pattern="Keep harness_mem/mcp/server.py stdout-clean for JSON-RPC.",
        trigger="When editing MCP tool wiring",
        source_candidate_id="candidate-file-context",
    )
    run(backend.structured_store.save_confirmed_rule(rule))

    handoff = TaskHandoff(
        project_name=project_name,
        task_id="file-context-task",
        summary="Continue file_context implementation in harness_mem/mcp/server.py",
        context={"files": [relative_path]},
    )
    run(backend.structured_store.save_task_handoff(handoff))

    skill = Skill(
        project_name=project_name,
        name="MCP stdout guardrail",
        activation_condition="When touching harness_mem/mcp/server.py",
        steps=["Do not print on stdout from MCP handlers."],
        termination_condition="File-context wiring is validated.",
    )
    run(backend.structured_store.save_skill(skill))

    result = run(build_file_context(backend, project_name=project_name, path=query_path))

    assert result.project_name == project_name
    assert result.normalized_path.endswith(relative_path)
    assert result.stale_file_signal.state == "newer_activity_exists"
    assert result.cost_hint.estimated_tokens > 0
    assert result.cost_hint.disclosure_level in {"L0", "L1", "L2", "L3", "L4+"}

    kinds = {item.kind for item in result.items}
    assert {
        "project_profile_key_file",
        "observation",
        "memory_entry",
        "confirmed_rule",
        "task_handoff",
        "skill_hint",
    }.issubset(kinds)

    key_file_item = next(item for item in result.items if item.kind == "project_profile_key_file")
    assert key_file_item.source_ids == [profile.id]

    observation_item = next(item for item in result.items if item.kind == "observation")
    assert observation_item.source_ids == [observation.id]
    assert observation_item.drilldown is not None
    assert observation_item.drilldown.read_surface == "read_api.get_observations"

    current_truth_item = next(
        item
        for item in result.items
        if item.kind == "memory_entry" and item.source_ids == [current_entry.id]
    )
    assert current_truth_item.truth_status == "confirmed_current"

    historical_truth_item = next(
        item
        for item in result.items
        if item.kind == "memory_entry" and item.source_ids == [historical_entry.id]
    )
    assert historical_truth_item.truth_status == "historical"

    skill_item = next(item for item in result.items if item.kind == "skill_hint")
    assert skill_item.source_ids == [skill.id]
    assert "MCP stdout guardrail" in skill_item.summary
    assert "Do not print on stdout" not in skill_item.summary


def test_build_file_context_marks_historical_path_queries_without_current_truth(
    backend: LocalMemoryBackend,
) -> None:
    project_name = "file-context-renamed"
    current_path = "harness_mem/mcp/server.py"
    old_path = "legacy/mcp_server.py"

    _seed_profile(backend, project_name=project_name, key_files=[current_path])
    observation = Observation(
        session_id="renamed-session",
        client="codex",
        raw_content="The old MCP server lived in legacy/mcp_server.py before the move.",
        content_type="transcript",
        metadata={"project_name": project_name},
    )
    run(backend.verbatim_store.save(observation))
    historical_entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="legacy/mcp_server.py handled MCP routing before it was renamed.",
        source="manual",
        valid_to=datetime.now(timezone.utc) - timedelta(days=1),
    )
    run(backend.structured_store.save_memory_entry(historical_entry))

    result = run(build_file_context(backend, project_name=project_name, path=old_path))

    assert result.items
    assert all(item.truth_status != "confirmed_current" for item in result.items)
    assert any(item.truth_status == "historical" for item in result.items)
    assert result.stale_file_signal.state == "historical_path_match"
