"""Evidence, timeline, skill, and relation read MCP handlers."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Literal

from harness_mem.commands import support as _support
from harness_mem.file_context import build_file_context
from harness_mem.read_api import (
    query_temporal_truth,
    regex_search_observations,
    search_skills,
    serialize_observation,
    serialize_regex_observation_match,
    serialize_relation_path,
    serialize_skill,
    serialize_temporal_query_result,
    serialize_timeline_observation,
    timeline_observations,
    trace_relation_paths,
)
from harness_mem.recall import build_trace_recall_result
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

from .handler_facade_proxy import tool_handlers_facade as _core
from .read_query_support import _record_temporal_quality_signals


def _get_backend():
    return _core._get_backend()


def _observer_data_dir():
    return _core._observer_data_dir()


def _cost_surface_budgets(project_name):
    return _core._cost_surface_budgets(project_name)


def _record_state_event(*args, **kwargs):
    return _core._record_state_event(*args, **kwargs)


def _run_command_to_payload(coro):
    return _core._run_command_to_payload(coro)


async def _gather_project_status(*args, **kwargs):
    return await _core._gather_project_status(*args, **kwargs)


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})
VALID_CONTEXT_OUTCOMES: frozenset[str] = frozenset({"used", "ignored", "misleading"})
CONTEXT_OUTCOME_VALUES: dict[str, float] = {
    "used": 1.0,
    "ignored": 0.0,
    "misleading": -1.0,
}
VALID_RETRIEVAL_PROFILES: frozenset[str] = frozenset({"light", "quality"})
RetrievalProfile = Literal["light", "quality"]


def tool_timeline(project_name: str, limit: int = 50) -> dict:
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


def tool_trace_relations(
    project_name: str,
    source_entity: str,
    relation_type: str | None = None,
    max_depth: int = 2,
    limit: int = 10,
    min_confidence: float = 0.0,
    include_history: bool = False,
) -> dict:
    """Return bounded relation paths starting at a source entity."""
    backend = _get_backend()
    try:
        paths = asyncio.run(
            trace_relation_paths(
                backend,
                project_name=project_name,
                source_entity=source_entity,
                relation_type=relation_type,
                max_depth=max_depth,
                limit=limit,
                min_confidence=min_confidence,
                include_history=include_history,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    serialized_paths = [serialize_relation_path(path) for path in paths]
    recall_result = build_trace_recall_result(
        project_name=project_name,
        source_entity=source_entity,
        relation_type=relation_type,
        paths=serialized_paths,
    )
    return {
        "success": True,
        "project_name": project_name,
        "source_entity": source_entity,
        "relation_type": relation_type,
        "max_depth": max_depth,
        "limit": limit,
        "include_history": include_history,
        "paths": serialized_paths,
        "path_count": len(paths),
        "recall": recall_result.to_dict(),
    }


def tool_temporal_query(
    project_name: str,
    query: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    truth_type: str | None = None,
    mode: str = "current",
    as_of: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    recorded_from: str | None = None,
    recorded_to: str | None = None,
    limit: int = 20,
    require_unique_current: bool = False,
) -> dict:
    """Query the v3.3 temporal read model without mutating truth."""
    if mode not in {"current", "history", "as_of"}:
        return {
            "success": False,
            "error": "mode must be one of: current, history, as_of",
        }
    if truth_type not in {None, "memory_entry", "relation_fact", "confirmed_rule"}:
        return {
            "success": False,
            "error": "truth_type must be one of: memory_entry, relation_fact, confirmed_rule",
        }
    parsed_as_of, error = _parse_optional_iso_datetime(as_of, "as_of")
    if error:
        return {"success": False, "error": error}
    if mode == "as_of" and parsed_as_of is None:
        return {"success": False, "error": "as_of is required when mode=as_of"}
    parsed_valid_from, error = _parse_optional_iso_datetime(valid_from, "valid_from")
    if error:
        return {"success": False, "error": error}
    parsed_valid_to, error = _parse_optional_iso_datetime(valid_to, "valid_to")
    if error:
        return {"success": False, "error": error}
    parsed_recorded_from, error = _parse_optional_iso_datetime(
        recorded_from, "recorded_from"
    )
    if error:
        return {"success": False, "error": error}
    parsed_recorded_to, error = _parse_optional_iso_datetime(recorded_to, "recorded_to")
    if error:
        return {"success": False, "error": error}

    backend = _get_backend()
    result = asyncio.run(
        query_temporal_truth(
            backend,
            project_name=project_name,
            query=query,
            subject=subject,
            predicate=predicate,
            truth_type=truth_type,
            mode=mode,
            as_of=parsed_as_of,
            valid_range=(parsed_valid_from, parsed_valid_to),
            recorded_range=(parsed_recorded_from, parsed_recorded_to),
            limit=limit,
            require_unique_current=require_unique_current,
        )
    )
    asyncio.run(
        _record_temporal_quality_signals(
            backend,
            project_name=project_name,
            result=result,
            mode=mode,
            identity_parts=(query, subject, predicate, truth_type, mode),
        )
    )
    payload = serialize_temporal_query_result(result)
    payload.update(
        {
            "project_name": project_name,
            "query": query,
            "subject": subject,
            "predicate": predicate,
            "truth_type": truth_type,
            "mode": mode,
            "as_of": parsed_as_of.isoformat() if parsed_as_of else None,
            "valid_range": {
                "start": parsed_valid_from.isoformat() if parsed_valid_from else None,
                "end": parsed_valid_to.isoformat() if parsed_valid_to else None,
            },
            "recorded_range": {
                "start": parsed_recorded_from.isoformat()
                if parsed_recorded_from
                else None,
                "end": parsed_recorded_to.isoformat() if parsed_recorded_to else None,
            },
        }
    )
    return payload


def _parse_optional_iso_datetime(
    value: str | None, field_name: str
) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{field_name} must be an ISO datetime"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, None


def tool_search_raw(
    pattern: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 20,
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


def tool_search_skills(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 10,
    include_shared: bool = False,
    shared_scope: str = "exclude",
) -> dict:
    """Search confirmed procedural skills."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }
    if shared_scope not in {"exclude", "include", "only"}:
        return {
            "success": False,
            "error": "shared_scope must be one of: exclude, include, only",
        }

    effective_shared_scope = shared_scope
    if include_shared and shared_scope == "exclude":
        effective_shared_scope = "include"

    backend = _get_backend()
    skills = asyncio.run(
        search_skills(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            limit=limit,
            shared_scope=effective_shared_scope,
        )
    )
    return {
        "success": True,
        "project_name": project_name,
        "query": query,
        "scope": scope,
        "include_shared": include_shared,
        "shared_scope": effective_shared_scope,
        "limit": limit,
        "skills": [serialize_skill(skill) for skill in skills],
        "count": len(skills),
    }


def tool_get_skill(skill_id: str) -> dict:
    """Return a full confirmed skill payload by id."""
    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.get_skill(skill_id))
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    return {
        "success": True,
        "skill": serialize_skill(skill),
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
        backend.verbatim_store.list(limit=10000, project_name=project_name)
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


def tool_get_task_handoffs(project_name: str, limit: int = 5) -> dict:
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


def tool_get_confirmed_rules(project_name: str, include_history: bool = False) -> dict:
    """Return all confirmed rules for a project."""
    backend = _get_backend()
    rules = asyncio.run(
        backend.structured_store.list_confirmed_rules(
            project_name,
            include_history=include_history,
        )
    )
    return {
        "project_name": project_name,
        "include_history": include_history,
        "rules": [
            {
                "id": r.id,
                "pattern": r.pattern,
                "trigger": r.trigger,
                "examples": r.examples,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "supersedes": r.supersedes,
                "superseded_by": r.superseded_by,
                "is_historical": bool(
                    r.valid_to and r.valid_to <= datetime.now(timezone.utc)
                ),
                "tags": r.tags,
                "provenance": r.provenance,
            }
            for r in rules
        ],
        "count": len(rules),
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
