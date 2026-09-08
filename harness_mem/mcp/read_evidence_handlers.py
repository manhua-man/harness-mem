"""Evidence, timeline, task, profile, and file-context MCP handlers."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from harness_mem.commands import support as _support
from harness_mem.file_context import build_file_context
from harness_mem.read_api import (
    regex_search_observations,
    serialize_observation,
    serialize_regex_observation_match,
    serialize_timeline_observation,
    timeline_observations,
)
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

from .handler_facade_proxy import tool_handlers_facade as _core


def _get_backend():
    return _core._get_backend()


def tool_timeline(project_name: str, limit: int | None = None) -> dict:
    """Return chronological observation timeline for a project."""
    backend = _get_backend()
    obs_list = asyncio.run(
        timeline_observations(backend, project_name=project_name, limit=limit)
    )

    return {
        "project_name": project_name,
        "limit": limit,
        "observations": [
            serialize_timeline_observation(observation) for observation in obs_list
        ],
        "count": len(obs_list),
    }


def tool_search_raw(
    pattern: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int | None = None,
) -> dict:
    """Regex search raw observation evidence."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    backend = _get_backend()
    try:
        matches = asyncio.run(
            regex_search_observations(
                backend,
                project_name=project_name,
                pattern=pattern,
                scope=scope,
                limit=limit,
            )
        )
    except re.error as exc:
        return {"success": False, "error": f"invalid regex: {exc}"}

    return {
        "success": True,
        "project_name": project_name,
        "pattern": pattern,
        "scope": scope,
        "limit": limit,
        "matches": [serialize_regex_observation_match(match) for match in matches],
        "count": len(matches),
    }


def tool_get_observations(
    project_name: str,
    session_id: str | None = None,
    observation_ids: list[str] | None = None,
) -> dict:
    """Return project observations by session id or explicit observation ids."""

    requested_ids = [
        value.removeprefix("O-").strip()
        for value in observation_ids or []
        if value and value.strip()
    ]
    if not session_id and not requested_ids:
        return {
            "success": False,
            "project_name": project_name,
            "error": "session_id or observation_ids is required",
        }

    backend = _get_backend()
    project_obs = asyncio.run(
        backend.verbatim_store.list(limit=None, project_name=project_name)
    )
    unresolved_ids: list[str] = []
    if requested_ids:
        selected: list[Any] = []
        for requested_id in requested_ids:
            matches = [
                observation
                for observation in project_obs
                if observation.id == requested_id
                or observation.id.startswith(requested_id)
            ]
            if len(matches) == 1:
                selected.append(matches[0])
            else:
                unresolved_ids.append(requested_id)
        observations = selected
    else:
        observations = [
            observation
            for observation in project_obs
            if observation.session_id == session_id
        ]

    return {
        "success": True,
        "project_name": project_name,
        "session_id": session_id,
        "observation_ids": requested_ids,
        "unresolved_ids": unresolved_ids,
        "observations": [
            serialize_observation(observation) for observation in observations
        ],
        "count": len(observations),
    }


def tool_get_task_handoffs(project_name: str, limit: int | None = None) -> dict:
    """Return recent task handoffs for a project."""
    backend = _get_backend()
    handoffs = asyncio.run(
        backend.structured_store.get_latest_handoffs(project_name, limit=limit)
    )
    return {
        "project_name": project_name,
        "limit": limit,
        "handoffs": [
            {
                "id": h.id,
                "task_id": h.task_id,
                "summary": h.summary,
                "status": h.status,
                "next_steps": h.next_steps,
                "blockers": h.blockers,
                "last_activity": h.last_activity.isoformat()
                if h.last_activity
                else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "provenance": h.provenance,
            }
            for h in handoffs
        ],
        "count": len(handoffs),
    }


def tool_get_project_profile(project_name: str) -> dict:
    """Return the project profile for a project."""

    store = asyncio.run(
        LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name)
    )
    if store is None:
        return {"project_name": project_name, "found": False}

    profile = store
    return {
        "found": True,
        "project_name": profile.project_name,
        "description": profile.description,
        "stacks": profile.stacks,
        "key_files": profile.key_files,
        "retrieval_profile": profile.retrieval_profile,
    }


def tool_file_context(
    path: str,
    project_name: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Return compact, source-attributed memory already associated with a path."""
    backend = _get_backend()
    try:
        result = asyncio.run(
            build_file_context(
                backend,
                project_name=project_name,
                path=path,
                project_root=project_root,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    payload = result.to_dict()
    payload["success"] = True
    return payload
