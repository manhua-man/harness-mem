"""Onboarding-oriented CLI commands."""

from __future__ import annotations

from pathlib import Path

from harness_mem.commands.ingest import cmd_ingest
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    can_prompt,
    claude_session_count,
    codex_scope_note,
    codex_session_count,
    ensure_data_dir,
    ensure_project_profile,
    get_active_project,
    log_next_step_shown,
    print_recent_sessions,
    project_state,
    prompt_text,
    recent_claude_sessions,
    recent_codex_sessions,
    resolve_project_name,
    set_active_project,
    suggested_next_step,
)


async def cmd_quickstart(
    project_name: str | None = None,
    client: str = "auto",
    limit: int = 5,
) -> int:
    """Initialize harness-mem and guide the user into their first ingest."""
    ensure_data_dir()
    default_project = project_name or get_active_project() or Path.cwd().name
    if not project_name and can_prompt():
        project_name = prompt_text("Project name", default=default_project)
    else:
        project_name = default_project

    project_name = resolve_project_name(project_name, action_label="quickstart")
    if not project_name:
        return 1

    set_active_project(project_name)
    print(f"Quickstart for project: {project_name}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")

    profile, source_root = await ensure_project_profile(project_name)
    if profile and source_root:
        print(f"Profile detected from: {source_root}")
    elif profile:
        print("Profile already exists.")
    else:
        print("No local project profile detected yet.")

    claude_sessions = recent_claude_sessions(project_name, limit=limit or 3)
    codex_sessions = recent_codex_sessions(limit=limit or 3)
    claude_count = claude_session_count(project_name)
    codex_count = codex_session_count()
    print(f"Claude Code sessions: {claude_count}")
    print(f"Codex sessions (global): {codex_count}")
    print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
    print_recent_sessions("Recent Codex sessions (global):", codex_sessions)
    if codex_count:
        print(f"Note: {codex_scope_note()}")

    selected_client = _choose_quickstart_client(
        requested_client=client,
        claude_count=claude_count,
        codex_count=codex_count,
    )

    if selected_client == "claude-code" and claude_count == 0:
        print("No Claude Code sessions found for this project, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex" and codex_count == 0:
        print("No Codex sessions found, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex":
        print(f"Note: {codex_scope_note()}")

    if selected_client != "skip":
        ingest_result = await cmd_ingest(selected_client, project_name, limit)
        if ingest_result != 0:
            return ingest_result
    else:
        if client == "auto" and claude_count == 0 and codex_count > 0:
            print("Auto-ingest skipped for Codex because those sessions are not project-scoped.")
        print("Ingest skipped.")

    state = await project_state(project_name)
    next_command, reason = suggested_next_step(
        project_name=project_name,
        observation_count=state["observations"],
        memory_entry_count=state["memory_entries"],
        claude_sessions=claude_sessions,
        codex_sessions=codex_sessions,
    )

    print()
    print("📍 Phase: Quickstart Complete")
    print(f"→ Next: {next_command}")
    print(f"   Why: {reason}")
    print("Also useful:")
    print("  harness-mem doctor")
    log_next_step_shown(project_name, "quickstart", next_command)
    return 0


def _choose_quickstart_client(
    *,
    requested_client: str,
    claude_count: int,
    codex_count: int,
) -> str:
    selected_client = requested_client
    if selected_client == "auto":
        if claude_count > 0:
            return "claude-code"
        if codex_count > 0:
            return "skip"
        return "skip"
    return selected_client
