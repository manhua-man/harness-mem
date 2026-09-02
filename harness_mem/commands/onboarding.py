"""Onboarding-oriented CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from harness_mem.commands.ingest import cmd_ingest
from harness_mem.commands.support import (
    can_prompt,
    detect_runtime_client,
    ensure_data_dir,
    ensure_project_profile,
    get_active_project,
    prompt_text,
    resolve_project_name,
    set_active_project,
)
from harness_mem.integration.command_sync import CommandHost, command_hint
from harness_mem.integration.repair import repair_integrations


async def cmd_quickstart(
    project_name: str | None = None,
    client: str = "auto",
    limit: int = 0,
) -> int:
    """Connect the current project and install the current host's memory entry."""
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
    profile, source_root = await ensure_project_profile(project_name, cwd_root)
    if profile is None:
        print("Could not connect this project.")
        return 1
    workspace_root = (source_root or cwd_root).resolve()
    selected_client = detect_runtime_client() if client == "auto" else client

    if selected_client is None:
        print(
            "Could not detect the current app. Run quickstart again with --client "
            "and the app name, for example: harness-mem quickstart --client cursor."
        )
        return 1

    if selected_client == "skip":
        print(f"Project connected: {project_name}. Host integration was skipped.")
        return 0

    host_client = cast(CommandHost, selected_client)
    report = repair_integrations(
        clients=(host_client,),
        project_root=workspace_root,
    )
    if not report.success:
        print("Could not finish setup. Run harness-mem doctor for details.")
        return 1

    if limit > 0:
        ingest_result = await cmd_ingest(
            host_client,
            project_name,
            limit,
            project_root=str(workspace_root),
        )
        if ingest_result != 0:
            return ingest_result
    hint = command_hint(host_client)
    print(
        f"Installed {hint} and project Hooks for {project_name}. "
        f'Start a new task, then use {hint}, for example: "remember this session".'
    )
    return 0
