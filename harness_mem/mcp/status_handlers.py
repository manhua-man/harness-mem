"""Project readiness and first-use workspace preparation."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
from harness_mem.commands import support as _support
from harness_mem.commands.integration_cmds import (
    SUPPORTED_HOOK_CLIENTS,
    cmd_install_hook_suite,
)
from harness_mem.commands.support import (
    get_active_project,
    normalize_client_name,
    resolve_project_context,
    set_active_project,
)
from .handler_facade_proxy import tool_handlers_facade as _core


def _get_backend():
    return _core._get_backend()


_STATUS_BOOTSTRAP_HOSTS = frozenset(SUPPORTED_HOOK_CLIENTS)


def _bootstrap_status_workspace(
    *,
    project_name: str | None,
    project_root: str | None,
    host_client: str | None,
) -> tuple[str | None, Path | None, str | None, bool, str | None]:
    """Resolve and idempotently bootstrap context supplied by a live Agent."""

    root_context = (
        resolve_project_context(
            None,
            project_root=project_root,
            required=False,
            action_label="get_project_status",
        )
        if project_root
        else None
    )
    resolved_root = root_context.project_root if root_context is not None else None
    resolved_project = project_name or (
        root_context.project_name if root_context is not None else get_active_project()
    )
    host = normalize_client_name(host_client) if host_client else None

    if resolved_project is None or resolved_root is None:
        return resolved_project, resolved_root, host, False, None

    try:
        asyncio.run(
            _support.ensure_project_profile(resolved_project, project_root=resolved_root)
        )
        set_active_project(resolved_project)
    except PermissionError:
        return resolved_project, resolved_root, host, False, "project_permission"
    except OSError:
        return resolved_project, resolved_root, host, False, "project_unavailable"
    except ValueError:
        return resolved_project, resolved_root, host, False, "project_invalid"

    if host not in _STATUS_BOOTSTRAP_HOSTS:
        return resolved_project, resolved_root, host, False, None

    install_output = io.StringIO()
    with (
        contextlib.redirect_stdout(install_output),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        install_status = cmd_install_hook_suite(host, str(resolved_root), False, scope="user")
    failure_kind = None
    try:
        report = json.loads(install_output.getvalue())
        failure_kind = next(
            (item.get("error_kind") for item in report.get("results", [])
             if item.get("status") in {"failed", "unsupported"}),
            None,
        )
    except (AttributeError, TypeError, json.JSONDecodeError):
        pass
    return resolved_project, resolved_root, host, install_status == 0, failure_kind


def tool_get_project_status(
    project_name: str | None = None,
    project_root: str | None = None,
    host_client: str | None = None,
) -> dict:
    """Prepare the current project when needed and report whether it is ready."""

    resolved_project, resolved_root, resolved_host, hook_ready, failure_kind = (
        _bootstrap_status_workspace(
            project_name=project_name,
            project_root=project_root,
            host_client=host_client,
        )
    )
    if not resolved_project or resolved_root is None:
        return {
            "success": False,
            "message": "Open the intended workspace and try again.",
        }

    if resolved_host not in _STATUS_BOOTSTRAP_HOSTS:
        return {
            "success": False,
            "project_name": resolved_project,
            "message": "This Agent cannot prepare the project Hook.",
            "action": "Use a supported Agent and try again.",
        }

    if not hook_ready:
        recoveries = {
            "project_permission": (
                "Project memory settings could not be prepared because access was denied.",
                "Check write access to the harness-mem data directory, then retry hm.",
            ),
            "project_unavailable": (
                "Project memory settings could not be opened or saved.",
                "Run harness-mem doctor before retrying hm.",
            ),
            "project_invalid": (
                "Project memory settings could not be read; existing files were preserved.",
                "Run harness-mem doctor to check the existing settings before editing them.",
            ),
            "conflict": (
                "Existing project Hook files were preserved because they conflict with setup.",
                "Run harness-mem doctor and compare the existing files with setup. "
                "Only after confirming they are unmodified generated files, update them "
                "with harness-mem integration hooks sync --client "
                f"{resolved_host} --project-root . --force from the intended workspace.",
            ),
            "permission": (
                "Project Hook files could not be written because access was denied.",
                "Check workspace write access, then retry hm.",
            ),
            "unavailable": (
                "The installed Hook program is unavailable.",
                "Run harness-mem doctor in the environment where harness-mem is installed.",
            ),
            "invalid": (
                "The project Hook configuration could not be read.",
                "Run harness-mem doctor to check the existing configuration before editing it.",
            ),
            "unsupported": (
                "This Agent's Hook integration is not available.",
                "Use a supported Agent; run harness-mem doctor to check host support.",
            ),
        }
        message, action = recoveries.get(
            failure_kind or "unknown",
            ("The project Hook could not be prepared; the cause is not yet known.",
             "Run harness-mem doctor."),
        )
        return {
            "success": False,
            "project_name": resolved_project,
            "message": message,
            "action": action,
        }

    try:
        backend = _get_backend()
    except (OSError, ValueError):
        return {
            "success": False,
            "project_name": resolved_project,
            "message": "Project memory storage could not be opened.",
            "action": "Run harness-mem doctor before retrying hm.",
        }
    if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
        return {
            "success": False,
            "project_name": resolved_project,
            "message": "Project memory storage is not ready.",
            "action": "Run harness-mem doctor.",
        }

    message = "Memory storage is ready; Hook files are prepared."
    if resolved_host == "codex":
        message += (
            " If not yet trusted, review user Hooks in Codex Settings, then start a new task."
        )
    return {
        "success": True,
        "project_name": resolved_project,
        "message": message,
    }
