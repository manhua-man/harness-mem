"""Onboarding-oriented CLI commands."""

from __future__ import annotations

from pathlib import Path

from harness_mem.commands.ingest import cmd_ingest
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    can_prompt,
    claude_session_count,
    current_agent_client,
    codex_scope_note,
    codex_session_count,
    cursor_session_count,
    ensure_data_dir,
    ensure_project_profile,
    get_active_project,
    grok_session_count,
    log_next_step_shown,
    print_recent_sessions,
    project_state,
    prompt_text,
    recent_claude_sessions,
    recent_cursor_sessions,
    recent_codex_sessions,
    recent_grok_sessions,
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
    cwd_root = Path.cwd()
    default_project = project_name or cwd_root.name or get_active_project()
    if not project_name and can_prompt():
        project_name = prompt_text("Project name", default=default_project)
    else:
        project_name = default_project

    project_name = resolve_project_name(
        project_name,
        project_root=cwd_root,
        action_label="quickstart",
    )
    if not project_name:
        return 1

    set_active_project(project_name)
    print(f"Quickstart for project: {project_name}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")

    profile, source_root = await ensure_project_profile(project_name, cwd_root)
    if profile and source_root:
        print(f"Profile detected from: {source_root}")
    elif profile:
        print("Profile already exists.")
    else:
        print("No local project profile detected yet.")

    workspace_root = source_root or Path.cwd()
    claude_sessions = recent_claude_sessions(project_name, limit=limit or 3)
    cursor_sessions = recent_cursor_sessions(workspace_root, limit=limit or 3)
    codex_sessions = recent_codex_sessions(workspace_root, limit=limit or 3)
    grok_sessions = recent_grok_sessions(workspace_root, limit=limit or 3)
    claude_count = claude_session_count(project_name)
    cursor_count = cursor_session_count(workspace_root)
    codex_count = codex_session_count(workspace_root)
    grok_count = grok_session_count(workspace_root)
    print(f"Claude Code sessions: {claude_count}")
    print(f"Cursor sessions (workspace-scoped): {cursor_count}")
    print(f"Codex sessions (workspace-scoped): {codex_count}")
    print(f"Grok sessions (workspace-scoped): {grok_count}")
    print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
    print_recent_sessions("Recent Cursor sessions:", cursor_sessions)
    print_recent_sessions("Recent Codex sessions:", codex_sessions)
    print_recent_sessions("Recent Grok sessions:", grok_sessions)
    if codex_count:
        print(f"Note: {codex_scope_note()}")

    selected_client = _choose_quickstart_client(
        requested_client=client,
        current_client=current_agent_client(),
        claude_count=claude_count,
        cursor_count=cursor_count,
        codex_count=codex_count,
        grok_count=grok_count,
    )

    if selected_client == "claude-code" and claude_count == 0:
        print("No Claude Code sessions found for this project, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "cursor" and cursor_count == 0:
        print("No Cursor sessions matched the current workspace, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex" and codex_count == 0:
        print("No Codex sessions matched the current workspace, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "grok" and grok_count == 0:
        print("No Grok sessions matched the current workspace, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex":
        print(f"Note: {codex_scope_note()}")

    if selected_client != "skip":
        ingest_result = await cmd_ingest(
            selected_client,
            project_name,
            limit,
            project_root=str(workspace_root),
        )
        if ingest_result != 0:
            return ingest_result
    else:
        print("Ingest skipped.")

    state = await project_state(project_name)
    next_command, reason = suggested_next_step(
        project_name=project_name,
        observation_count=state["observations"],
        memory_entry_count=state["memory_entries"],
        claude_sessions=claude_sessions,
        cursor_sessions=cursor_sessions,
        grok_sessions=grok_sessions,
        codex_sessions=codex_sessions,
        project_root=workspace_root,
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
    current_client: str,
    claude_count: int,
    cursor_count: int,
    codex_count: int,
    grok_count: int,
) -> str:
    selected_client = requested_client
    if selected_client == "auto":
        if current_client == "cursor" and cursor_count > 0:
            return "cursor"
        if current_client == "grok" and grok_count > 0:
            return "grok"
        if claude_count > 0:
            return "claude-code"
        if cursor_count > 0:
            return "cursor"
        if codex_count > 0:
            return "codex"
        if grok_count > 0:
            return "grok"
        return "skip"
    return selected_client
