#!/usr/bin/env python3
"""
harness-mem MCP Server — structured memory access for Claude Code
=================================================================
Install: claude mcp add harness-mem -- python -m harness_mem.mcp.server

Tools:
  search_memory          — search structured + verbatim memory
  timeline               — observation timeline
  get_observations      — list observations for a session
  get_task_handoffs     — recent task handoffs
  get_confirmed_rules   — confirmed rules for a project
  get_project_profile   — project profile
  get_project_status    — current project memory status and active project
  ingest_sessions       — project-scoped environment-aware session ingest
  prepare_session_distill — one-shot ingest + evidence packet for AI distill
  distill_sessions      — heuristic distill fallback for ingested sessions
  list_candidates       — pending/accepted/rejected review candidates
  auto_review_candidates — heuristic auto-confirm / auto-reject pass (preview or apply)
  create_rule_candidate — create a rule candidate
  confirm_rule          — promote candidate to confirmed rule
"""

import os
import sys

# --- MCP stdio protection -----------------------------------------------
# Redirect stdout → stderr before heavy imports so that any stray print()
# statements from dependencies never corrupt the JSON-RPC stream on stdout.
_REAL_STDOUT_FD = None
_REAL_STDOUT_ENCODING = sys.stdout.encoding or "utf-8"
_REAL_STDOUT_ERRORS = sys.stdout.errors or "replace"
try:
    _REAL_STDOUT_FD = os.dup(1)
    os.dup2(2, 1)
except (OSError, AttributeError):
    pass
sys.stdout = sys.stderr

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Callable, TypedDict  # noqa: E402

from harness_mem import __version__ as _HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.commands.auto_review import auto_review_candidates  # noqa: E402
from harness_mem.commands.distill import cmd_distill  # noqa: E402
from harness_mem.commands.ingest import cmd_ingest  # noqa: E402
from harness_mem.commands.support import get_active_project  # noqa: E402
from harness_mem.core.schemas import ProceduralCandidate, SupersedeCandidate  # noqa: E402
from harness_mem.read_api import (  # noqa: E402
    build_search_project_context_map,
    parse_relative_time_window,
    regex_search_observations,
    search_memory,
    search_relation_facts,
    search_skills,
    serialize_memory_entry_search_result,
    serialize_observation,
    serialize_observation_search_result,
    serialize_relation_path,
    serialize_regex_observation_match,
    serialize_relation_fact_search_result,
    serialize_skill,
    serialize_timeline_observation,
    timeline_observations,
    trace_relation_paths,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.storage.local_project_profile_store import (  # noqa: E402
    LocalProjectProfileStore,
)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("harness_mem_mcp")

DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"

# Singleton backend — initialized once per MCP server process lifetime.
_backend: LocalMemoryBackend | None = None


def _get_backend() -> LocalMemoryBackend:
    global _backend
    if _backend is None:
        _backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        # Synchronous init via asyncio.run since MCP handlers are sync.
        asyncio.run(_backend.init())
    return _backend


def set_backend_override(backend: LocalMemoryBackend | None) -> None:
    """Override the singleton backend (used by tests to inject tmp_path backend)."""
    global _backend
    _backend = backend


# =============================================================================
# READ TOOLS
# =============================================================================


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})


def tool_search_memory(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    mode: str = "auto",
    memory_type: list[str] | None = None,
    include_history: bool = False,
) -> dict:
    """Search structured memory entries + verbatim observations.

    v1.6.1: ``memory_type`` is an optional list filter ({episodic, semantic,
    procedural}). Empty / None disables the filter; values are OR-ed.
    """
    backend = _get_backend()

    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    if memory_type:
        normalized = [str(value).strip().lower() for value in memory_type]
        invalid = [value for value in normalized if value not in VALID_MEMORY_TYPES]
        if invalid:
            return {
                "success": False,
                "error": (
                    "unknown memory_type: " + ", ".join(sorted(set(invalid)))
                    + ". Valid: episodic | semantic | procedural."
                ),
            }
        memory_type = normalized
    else:
        memory_type = None

    parsed_time = parse_relative_time_window(query)
    entries, obs_list, relation_facts, tech_stack_by_project = asyncio.run(
        _gather_search_payload(
            backend,
            query=parsed_time.query,
            project_name=project_name,
            scope=scope,
            mode=mode,
            memory_type=memory_type,
            include_history=include_history,
            time_window=parsed_time.time_window,
        )
    )

    combined_results = entries or relation_facts or obs_list
    effective_mode = getattr(combined_results[0], "_search_mode", mode) if combined_results else mode
    fallback_reason = getattr(combined_results[0], "_search_fallback_reason", None) if combined_results else None

    return {
        "project_name": project_name,
        "query": query,
        "effective_query": parsed_time.query,
        "scope": scope,
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "include_history": include_history,
        "time_window": (
            {
                "start": parsed_time.start.isoformat() if parsed_time.start else None,
                "end": parsed_time.end.isoformat() if parsed_time.end else None,
                "phrase": parsed_time.phrase,
            }
            if parsed_time.time_window
            else None
        ),
        "memory_entries": [
            serialize_memory_entry_search_result(entry, mode, tech_stack_by_project)
            for entry in entries
        ],
        "relation_facts": [
            serialize_relation_fact_search_result(fact, tech_stack_by_project) for fact in relation_facts
        ],
        "observations": [
            serialize_observation_search_result(
                observation,
                mode,
                query,
                tech_stack_by_project,
            )
            for observation in obs_list
        ],
        "memory_entry_count": len(entries),
        "relation_fact_count": len(relation_facts),
        "observation_count": len(obs_list),
    }


async def _gather_search_payload(
    backend: LocalMemoryBackend,
    *,
    query: str,
    project_name: str | None,
    scope: str,
    mode: str,
    memory_type: list[str] | None = None,
    include_history: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
) -> tuple[
    list[Any],
    list[Any],
    list[Any],
    dict[str, list[str]],
]:
    """Collect every async dependency for tool_search_memory in a single loop.

    Previously each await spun up its own asyncio.run, which built and tore
    down the event loop four times per request. Consolidating keeps
    LocalMemoryBackend's connection pool warm for the duration of one call.
    """
    entries, obs_list = await search_memory(
        backend,
        project_name=project_name,
        query=query,
        scope=scope,
        mode=mode,
        memory_entry_limit=20,
        observation_limit=20,
        memory_type=memory_type,
        include_history=include_history,
        time_window=time_window,
    )
    relation_facts = await search_relation_facts(
        backend,
        project_name=project_name,
        query=query,
        scope=scope,
        limit=20,
        include_history=include_history,
        time_window=time_window,
    )
    for entry in entries:
        await backend.structured_store.touch_memory_entry(entry.id)
    tech_stack_by_project = await build_search_project_context_map(
        backend,
        entries=entries,
        observations=obs_list,
        relation_facts=relation_facts,
    )
    return entries, obs_list, relation_facts, tech_stack_by_project


def tool_timeline(project_name: str, limit: int = 50) -> dict:
    """Return chronological observation timeline for a project."""
    backend = _get_backend()
    obs_list = asyncio.run(timeline_observations(backend, project_name=project_name, limit=limit))

    return {
        "project_name": project_name,
        "limit": limit,
        "observations": [serialize_timeline_observation(observation) for observation in obs_list],
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

    return {
        "success": True,
        "project_name": project_name,
        "source_entity": source_entity,
        "relation_type": relation_type,
        "max_depth": max_depth,
        "limit": limit,
        "include_history": include_history,
        "paths": [serialize_relation_path(path) for path in paths],
        "path_count": len(paths),
    }


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
        return {"success": False, "error": "project_name is required when scope=project"}

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
) -> dict:
    """Search confirmed procedural skills."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}

    backend = _get_backend()
    skills = asyncio.run(
        search_skills(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            limit=limit,
        )
    )
    return {
        "success": True,
        "project_name": project_name,
        "query": query,
        "scope": scope,
        "limit": limit,
        "skills": [serialize_skill(skill) for skill in skills],
        "count": len(skills),
    }


def tool_get_observations(project_name: str, session_id: str) -> dict:
    """List all observations for a given session."""
    backend = _get_backend()
    all_obs = asyncio.run(backend.verbatim_store.list(limit=10000))
    session_obs = [
        o
        for o in all_obs
        if o.session_id == session_id
        and o.metadata.get("project_name") == project_name
    ]

    return {
        "project_name": project_name,
        "session_id": session_id,
        "observations": [serialize_observation(observation) for observation in session_obs],
        "count": len(session_obs),
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
                "last_activity": h.last_activity.isoformat() if h.last_activity else None,
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
                "is_historical": bool(r.valid_to and r.valid_to <= datetime.now(timezone.utc)),
                "tags": r.tags,
                "provenance": r.provenance,
            }
            for r in rules
        ],
        "count": len(rules),
    }


def tool_get_project_profile(project_name: str) -> dict:
    """Return the project profile for a project."""
    store = asyncio.run(LocalProjectProfileStore(DEFAULT_DATA_DIR).get(project_name))
    if store is None:
        return {"project_name": project_name, "found": False}

    profile = store
    return {
        "found": True,
        "project_name": profile.project_name,
        "description": profile.description,
        "stacks": profile.stacks,
        "key_files": profile.key_files,
    }


async def _gather_project_status(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=5)
    confirmed_rules = await backend.structured_store.list_confirmed_rules(project_name)
    pending_rules = await backend.structured_store.list_rule_candidates(
        project_name,
        status="pending",
    )
    pending_entries = await backend.structured_store.list_memory_entries(
        project_name,
        status="pending",
        limit=100000,
    )
    pending_facts = await backend.structured_store.list_relation_facts(
        project_name,
        status="pending",
        limit=100000,
    )
    return {
        "observation_count": len(project_observations),
        "memory_entry_count": len(memory_entries),
        "task_handoff_count": len(handoffs),
        "confirmed_rule_count": len(confirmed_rules),
        "pending_candidate_count": len(pending_rules) + len(pending_entries) + len(pending_facts),
    }


def tool_get_project_status(project_name: str | None = None) -> dict:
    """Return active project and memory counts without requiring CLI status."""
    active_project = get_active_project()
    resolved_project = project_name or active_project
    if not resolved_project:
        return {
            "success": False,
            "active_project": active_project,
            "error": "project_name is required when no active project is set",
        }

    backend = _get_backend()
    counts = asyncio.run(_gather_project_status(backend, resolved_project))
    return {
        "success": True,
        "project_name": resolved_project,
        "active_project": active_project,
        **counts,
    }


def _run_command_to_payload(coro: Any) -> dict[str, Any]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = asyncio.run(coro)
    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": output.getvalue().strip(),
    }


def tool_ingest_sessions(
    project_name: str,
    client: str = "auto",
    limit: int = 10,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
) -> dict:
    """Ingest sessions through MCP so users do not need to drive CLI commands."""
    if client not in {"auto", "claude-code", "codex", "codex-archive"}:
        return {
            "success": False,
            "error": "client must be one of: auto, claude-code, codex, codex-archive",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}

    payload = _run_command_to_payload(
        cmd_ingest(
            client,
            project_name,
            limit,
            full_rescan,
            scope=scope,
            project_root=project_root,
        )
    )
    return {
        "project_name": project_name,
        "client": client,
        "scope": scope,
        "limit": limit,
        **payload,
    }


async def _recent_project_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
) -> list[Any]:
    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    return sorted(
        project_observations,
        key=lambda observation: observation.timestamp or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:limit]


def _truncate_packet_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return f"{value[:max_chars]}\n\n[TRUNCATED: {omitted} chars omitted]"


def tool_prepare_session_distill(
    project_name: str,
    client: str = "auto",
    limit: int = 5,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
    observation_limit: int = 5,
    max_chars_per_observation: int = 6000,
    run_ingest: bool = True,
) -> dict:
    """Prepare a compact evidence packet for AI-led session-distill.

    This intentionally stops before synthesis. The model should read the
    returned observations, decide what deserves a pending candidate, then call
    suggest_* tools. Keeping the discovery work in one MCP call avoids slash
    commands probing files, shell aliases, timeline, and observation IDs by hand.
    """
    if client not in {"auto", "claude-code", "codex", "codex-archive"}:
        return {
            "success": False,
            "error": "client must be one of: auto, claude-code, codex, codex-archive",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}

    effective_limit = max(1, min(int(limit), 50))
    effective_observation_limit = max(1, min(int(observation_limit), 20))
    effective_max_chars = max(500, min(int(max_chars_per_observation), 20000))

    ingest_payload: dict[str, Any] = {
        "success": True,
        "skipped": True,
        "reason": "run_ingest=false",
    }
    if run_ingest:
        ingest_payload = tool_ingest_sessions(
            project_name=project_name,
            client=client,
            limit=effective_limit,
            full_rescan=full_rescan,
            scope=scope,
            project_root=project_root,
        )

    backend = _get_backend()
    observations = asyncio.run(
        _recent_project_observations(
            backend,
            project_name=project_name,
            limit=effective_observation_limit,
        )
    )
    counts = asyncio.run(_gather_project_status(backend, project_name))

    packet_observations = []
    for observation in observations:
        packet_observations.append(
            {
                "source": f"observation:{observation.id}",
                "id": observation.id,
                "session_id": observation.session_id,
                "client": observation.client,
                "content_type": observation.content_type,
                "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
                "tags": observation.tags,
                "metadata": observation.metadata,
                "raw_content": _truncate_packet_text(
                    observation.raw_content,
                    effective_max_chars,
                ),
            }
        )

    return {
        "success": bool(packet_observations) or bool(ingest_payload.get("success")),
        "project_name": project_name,
        "project_root": project_root,
        "client": client,
        "scope": scope,
        "limit": effective_limit,
        "ingest": ingest_payload,
        "status": counts,
        "observation_limit": effective_observation_limit,
        "max_chars_per_observation": effective_max_chars,
        "observations": packet_observations,
        "observation_count": len(packet_observations),
        "distill_instructions": [
            "Do not call Bash, cmem, cat, ls, find, timeline, or get_observations for this slash flow unless this packet is empty.",
            "Read the observations in this response as the session-distill evidence packet.",
            "Do not create candidates from tool probing, failed commands, MCP/slash mechanics, or agent orchestration failures unless the target project is that tooling.",
            "For application/game projects, do not record AI review workflows or skill names as project architecture.",
            "Create only reusable pending candidates with suggest_memory_entry, suggest_rule, suggest_relation_fact, or create_task_handoff.",
            "Use source values from this packet, e.g. observation:<id>, unless a stronger session/file source is present.",
            "Finish by calling list_candidates(project_name, status='pending') once.",
        ],
    }


def tool_distill_sessions(
    project_name: str,
    session_id: str | None = None,
    category: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Run heuristic distill through MCP as a fallback to AI session-distill."""
    if category is not None and category not in {"architecture", "convention", "api", "bug", "decision"}:
        return {
            "success": False,
            "error": "category must be one of: architecture, convention, api, bug, decision",
        }

    payload = _run_command_to_payload(
        cmd_distill(
            project_name,
            session_id,
            category=category,
            project_root=project_root,
        )
    )
    return {
        "project_name": project_name,
        "session_id": session_id,
        "category": category,
        "project_root": project_root,
        **payload,
    }


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_rule_candidate(candidate: Any) -> dict:
    return {
        "type": "rule",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "examples": candidate.examples,
        "confidence": candidate.confidence,
        "source_session_id": candidate.session_id,
        "created_at": _isoformat(candidate.created_at),
        "confirm_tool": "confirm_rule",
        "reject_tool": "reject_rule",
    }


def _serialize_memory_entry_candidate(entry: Any) -> dict:
    return {
        "type": "memory_entry",
        "id": entry.id,
        "project_name": entry.project_name,
        "status": entry.status,
        "category": entry.category,
        "memory_type": getattr(entry, "memory_type", None),
        "content": entry.content,
        "confidence": entry.confidence,
        "source": entry.source,
        "tags": entry.tags,
        "created_at": _isoformat(entry.created_at),
        "updated_at": _isoformat(entry.updated_at),
        "provenance": entry.provenance,
        "confirm_tool": "confirm_memory_entry",
        "reject_tool": "reject_memory_entry",
    }


def _serialize_relation_fact_candidate(fact: Any) -> dict:
    return {
        "type": "relation_fact",
        "id": fact.id,
        "project_name": fact.project_name,
        "status": fact.status,
        "source_entity": fact.source_entity,
        "target_entity": fact.target_entity,
        "relation_type": fact.relation_type,
        "evidence": fact.evidence,
        "source": fact.source,
        "confidence": fact.confidence,
        "tags": fact.tags,
        "created_at": _isoformat(fact.created_at),
        "updated_at": _isoformat(fact.updated_at),
        "provenance": fact.provenance,
        "confirm_tool": "confirm_relation_fact",
        "reject_tool": "reject_relation_fact",
    }


def _serialize_supersede_candidate(candidate: Any) -> dict:
    return {
        "type": "supersede",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "target_type": candidate.target_type,
        "target_id": candidate.target_id,
        "replacement_type": candidate.replacement_type,
        "replacement_id": candidate.replacement_id,
        "reason": candidate.reason,
        "evidence": candidate.evidence,
        "confidence": candidate.confidence,
        "source": candidate.source,
        "created_at": _isoformat(candidate.created_at),
        "reviewed_at": _isoformat(candidate.reviewed_at),
        "reviewer_id": candidate.reviewer_id,
        "confirm_tool": "confirm_supersede",
        "reject_tool": "reject_supersede",
    }


def _serialize_procedural_candidate(candidate: Any) -> dict:
    return {
        "type": "procedural",
        "id": candidate.id,
        "project_name": candidate.project_name,
        "status": candidate.status,
        "activation_condition": candidate.activation_condition,
        "steps": candidate.steps,
        "termination_condition": candidate.termination_condition,
        "success_examples": candidate.success_examples,
        "source_session_id": candidate.source_session_id,
        "source": candidate.source,
        "confidence": candidate.confidence,
        "created_at": _isoformat(candidate.created_at),
        "confirm_tool": "confirm_skill",
        "reject_tool": "reject_skill",
    }


async def _gather_candidate_payload(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    status: str,
    limit: int,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    rules = await backend.structured_store.list_rule_candidates(project_name, status=status)
    entries = await backend.structured_store.list_memory_entries(project_name, status=status, limit=limit)
    facts = await backend.structured_store.list_relation_facts(project_name, status=status, limit=limit)
    supersedes = await backend.structured_store.list_supersede_candidates(project_name, status=status)
    procedural = await backend.structured_store.list_procedural_candidates(project_name, status=status)
    return (
        [_serialize_rule_candidate(candidate) for candidate in rules[:limit]],
        [_serialize_memory_entry_candidate(entry) for entry in entries],
        [_serialize_relation_fact_candidate(fact) for fact in facts],
        [_serialize_supersede_candidate(candidate) for candidate in supersedes[:limit]],
        [_serialize_procedural_candidate(candidate) for candidate in procedural[:limit]],
    )


def tool_list_candidates(project_name: str, status: str = "pending", limit: int = 100) -> dict:
    """Return structured memory candidates for human review."""
    if status not in {"pending", "accepted", "rejected"}:
        return {
            "success": False,
            "error": "status must be one of: pending, accepted, rejected",
        }

    effective_limit = max(1, min(int(limit), 500))
    backend = _get_backend()
    (
        rule_candidates,
        memory_entries,
        relation_facts,
        supersede_candidates,
        procedural_candidates,
    ) = asyncio.run(
        _gather_candidate_payload(
            backend,
            project_name=project_name,
            status=status,
            limit=effective_limit,
        )
    )
    all_candidates = [
        *rule_candidates,
        *memory_entries,
        *relation_facts,
        *supersede_candidates,
        *procedural_candidates,
    ]
    all_candidates.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    candidates = all_candidates[:effective_limit]

    return {
        "success": True,
        "project_name": project_name,
        "status": status,
        "limit": effective_limit,
        "candidates": candidates,
        "rule_candidates": rule_candidates,
        "memory_entries": memory_entries,
        "relation_facts": relation_facts,
        "supersede_candidates": supersede_candidates,
        "procedural_candidates": procedural_candidates,
        "count": len(candidates),
        "total_count": len(all_candidates),
        "rule_count": len(rule_candidates),
        "memory_entry_count": len(memory_entries),
        "relation_fact_count": len(relation_facts),
        "supersede_count": len(supersede_candidates),
        "procedural_count": len(procedural_candidates),
    }


def tool_auto_review_candidates(project_name: str, apply: bool = False) -> dict:
    """Run conservative heuristic auto-review over the project's pending candidates.

    Returns the summary shape documented in `openspec/specs/mcp/spec.md`
    (auto_confirmed / auto_rejected / kept_pending / needs_user_confirmation).
    With ``apply=False`` the structured store is not modified — the response
    is what auto-review *would* do. With ``apply=True`` decisions are applied
    via the same status mutators users would invoke manually.
    """
    backend = _get_backend()
    summary = asyncio.run(
        auto_review_candidates(backend, project_name=project_name, apply=apply)
    )
    payload = summary.to_dict()
    payload["success"] = True
    payload["project_name"] = project_name
    payload["applied"] = bool(apply)
    return payload


# =============================================================================
# WRITE TOOLS
# =============================================================================


def tool_create_rule_candidate(
    project_name: str,
    session_id: str,
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
) -> dict:
    """Create a rule candidate from a correction."""
    from uuid import uuid4
    from harness_mem.core.schemas import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id,
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.6,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
    }


def tool_confirm_rule(rule_id: str) -> dict:
    """Promote a rule candidate to a confirmed rule."""
    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status == "accepted":
        return {"success": False, "error": f"Candidate already confirmed: {rule_id}"}

    confirmed = ConfirmedRule(
        id=str(uuid4()),
        project_name=candidate.project_name,
        pattern=candidate.pattern,
        trigger=candidate.trigger,
        examples=candidate.examples,
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=candidate.id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(confirmed))
    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "accepted"))

    return {
        "success": True,
        "confirmed_rule_id": confirmed.id,
        "pattern": confirmed.pattern,
        "trigger": confirmed.trigger,
    }


def tool_reject_rule(rule_id: str, reason: str | None = None) -> dict:
    """Reject a rule candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status in ("accepted", "rejected"):
        return {"success": False, "error": f"Candidate already processed: {rule_id}"}

    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "rejected"))
    return {
        "success": True,
        "rejected_rule_id": rule_id,
        "reason": reason or "No reason provided",
    }


def tool_suggest_supersede(
    project_name: str,
    target_type: str,
    target_id: str,
    replacement_type: str,
    replacement_id: str,
    reason: str,
    evidence: str,
    source: str = "",
    confidence: float = 0.7,
) -> dict:
    backend = _get_backend()
    candidate = SupersedeCandidate(
        project_name=project_name,
        target_type=target_type,
        target_id=target_id,
        replacement_type=replacement_type,
        replacement_id=replacement_id,
        reason=reason,
        evidence=evidence,
        source=source,
        confidence=confidence,
    )
    saved_id = asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "target_type": candidate.target_type,
        "target_id": candidate.target_id,
        "replacement_type": candidate.replacement_type,
        "replacement_id": candidate.replacement_id,
    }


def tool_confirm_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    confirmed = asyncio.run(backend.structured_store.confirm_supersede_candidate(candidate_id))
    if confirmed is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    return {
        "success": True,
        "candidate_id": confirmed.id,
        "status": confirmed.status,
    }


def tool_reject_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_supersede_candidate(candidate_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {candidate_id}"}
    updated = asyncio.run(backend.structured_store.update_supersede_candidate_status(candidate_id, "rejected"))
    if not updated:
        return {"success": False, "error": f"Failed to reject candidate: {candidate_id}"}
    return {
        "success": True,
        "rejected_candidate_id": candidate_id,
        "status": "rejected",
    }


def tool_suggest_rule(
    project_name: str,
    pattern: str,
    trigger: str,
    session_id: str | None = None,
    examples: list[str] | None = None,
) -> dict:
    """Suggest a rule candidate for later review (lighter than confirm_rule)."""
    from uuid import uuid4
    from harness_mem.core.schemas.rule_candidate import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id or "",
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.5,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "status": "suggested",
    }


def tool_suggest_skill(
    project_name: str,
    activation_condition: str,
    steps: list[str],
    termination_condition: str,
    success_examples: list[str] | None = None,
    source_session_id: str | None = None,
    source: str = "",
    confidence: float = 0.7,
) -> dict:
    """Suggest a procedural skill candidate for later review."""
    backend = _get_backend()
    candidate = ProceduralCandidate(
        project_name=project_name,
        activation_condition=activation_condition,
        steps=steps,
        termination_condition=termination_condition,
        success_examples=success_examples or [],
        source_session_id=source_session_id or "",
        source=source,
        confidence=confidence,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_procedural_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "status": "pending",
        "activation_condition": candidate.activation_condition,
    }


def tool_confirm_skill(candidate_id: str) -> dict:
    """Confirm a procedural skill candidate."""
    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.confirm_procedural_candidate(candidate_id))
    if skill is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    return {
        "success": True,
        "candidate_id": candidate_id,
        "skill": serialize_skill(skill),
    }


def tool_reject_skill(candidate_id: str) -> dict:
    """Reject a procedural skill candidate."""
    backend = _get_backend()
    updated = asyncio.run(
        backend.structured_store.update_procedural_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
    }


def tool_record_skill_result(skill_id: str, success: bool) -> dict:
    """Record one execution result for a confirmed skill."""
    backend = _get_backend()
    skill = asyncio.run(
        backend.structured_store.record_skill_result(
            skill_id,
            success=success,
        )
    )
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    return {
        "success": True,
        "skill": serialize_skill(skill),
    }


def tool_suggest_memory_entry(
    project_name: str,
    category: str,
    content: str,
    source: str,
    confidence: float = 0.7,
    tags: list[str] | None = None,
) -> dict:
    """Suggest a memory entry for later review."""
    from harness_mem.core.schemas.memory_entry import MemoryEntry
    backend = _get_backend()
    entry = MemoryEntry(
        project_name=project_name,
        category=category,
        content=content,
        source=source,
        confidence=confidence,
        status="pending",
        tags=tags or [],
    )
    saved_id = asyncio.run(backend.structured_store.save_memory_entry(entry))
    return {
        "success": True,
        "entry_id": saved_id,
        "category": entry.category,
        "status": "pending",
    }


def tool_confirm_memory_entry(entry_id: str) -> dict:
    """Confirm a pending memory entry."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_memory_entry_status(entry_id, "accepted"))
    return {"success": success, "entry_id": entry_id, "status": "accepted" if success else "not_found"}


def tool_reject_memory_entry(entry_id: str) -> dict:
    """Reject a pending memory entry."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_memory_entry_status(entry_id, "rejected"))
    return {"success": success, "entry_id": entry_id, "status": "rejected" if success else "not_found"}


def tool_suggest_relation_fact(
    project_name: str,
    source_entity: str,
    target_entity: str,
    relation_type: str,
    evidence: str,
    source: str,
    confidence: float = 0.7,
) -> dict:
    """Suggest a relation fact for later review."""
    from harness_mem.core.schemas.relation_fact import RelationFact
    backend = _get_backend()
    fact = RelationFact(
        project_name=project_name,
        source_entity=source_entity,
        target_entity=target_entity,
        relation_type=relation_type,
        evidence=evidence,
        source=source,
        confidence=confidence,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_relation_fact(fact))
    return {
        "success": True,
        "fact_id": saved_id,
        "relation": f"{source_entity} --{relation_type}--> {target_entity}",
        "status": "pending",
    }


def tool_confirm_relation_fact(fact_id: str) -> dict:
    """Confirm a pending relation fact."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_relation_fact_status(fact_id, "accepted"))
    return {"success": success, "fact_id": fact_id, "status": "accepted" if success else "not_found"}


def tool_reject_relation_fact(fact_id: str) -> dict:
    """Reject a pending relation fact."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_relation_fact_status(fact_id, "rejected"))
    return {"success": success, "fact_id": fact_id, "status": "rejected" if success else "not_found"}


def tool_create_task_handoff(
    project_name: str,
    task_id: str,
    summary: str,
    status: str,
    next_steps: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict:
    """Create a task handoff to record progress."""
    from harness_mem.core.schemas.task_handoff import TaskHandoff
    backend = _get_backend()
    handoff = TaskHandoff(
        project_name=project_name,
        task_id=task_id,
        summary=summary,
        status=status,
        next_steps=next_steps or [],
        blockers=blockers or [],
    )
    saved_id = asyncio.run(backend.structured_store.save_task_handoff(handoff))
    return {
        "success": True,
        "handoff_id": saved_id,
        "task_id": handoff.task_id,
    }


# =============================================================================
# MCP TOOL REGISTRY
# =============================================================================

import asyncio  # noqa: E402 (moved here so the stdio redirect above is clean)

class ToolSpec(TypedDict):
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


TOOLS: dict[str, ToolSpec] = {
    "search_memory": {
        "description": "Search structured memory entries and verbatim observations for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "enum": ["project", "all"], "description": "Search scope: project or all (default: project)"},
                "mode": {"type": "string", "enum": ["auto", "fts", "hybrid"], "description": "Search mode (default: auto)"},
                "memory_type": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
                    "description": "v1.6.1: optional filter on MemoryEntry.memory_type. Multiple values are OR-ed.",
                },
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.0: include historical structured truth. Default false returns current truth only.",
                    "default": False,
                },
            },
            "required": ["query"],
        },
        "handler": tool_search_memory,
    },
    "timeline": {
        "description": "Return chronological observation timeline for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "limit": {
                    "type": "integer",
                    "description": "Max observations to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_timeline,
    },
    "trace_relations": {
        "description": "Trace bounded current relation paths for a project entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "source_entity": {"type": "string", "description": "Relation source entity"},
                "relation_type": {
                    "type": "string",
                    "description": "Optional relation type filter, e.g. depends_on",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth (default 2, hard cap 3)",
                    "default": 2,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum paths to return (default 10)",
                    "default": 10,
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum edge confidence (default 0.0)",
                    "default": 0.0,
                },
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.2: include historical relation facts. Default false returns current relations only.",
                    "default": False,
                },
            },
            "required": ["project_name", "source_entity"],
        },
        "handler": tool_trace_relations,
    },
    "search_raw": {
        "description": "Regex search raw observation evidence with exact snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
                    "default": "project",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 20)",
                    "default": 20,
                },
            },
            "required": ["pattern"],
        },
        "handler": tool_search_raw,
    },
    "search_skills": {
        "description": "Search confirmed procedural skills.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "query": {"type": "string", "description": "Task or workflow query"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
                    "default": "project",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum skills to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        "handler": tool_search_skills,
    },
    "get_observations": {
        "description": "List all observations for a given session in a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID to filter by"},
            },
            "required": ["project_name", "session_id"],
        },
        "handler": tool_get_observations,
    },
    "get_task_handoffs": {
        "description": "Return recent task handoffs for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "limit": {
                    "type": "integer",
                    "description": "Max handoffs to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_get_task_handoffs,
    },
    "get_confirmed_rules": {
        "description": "Return all confirmed rules for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.0: include historical confirmed rules. Default false returns current rules only.",
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_get_confirmed_rules,
    },
    "get_project_profile": {
        "description": "Return the project profile for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
            },
            "required": ["project_name"],
        },
        "handler": tool_get_project_profile,
    },
    "get_project_status": {
        "description": "Return active project and memory counts without requiring CLI status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
            },
        },
        "handler": tool_get_project_status,
    },
    "ingest_sessions": {
        "description": "Ingest local agent sessions for a project through MCP.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "client": {
                    "type": "string",
                    "enum": ["auto", "claude-code", "codex", "codex-archive"],
                    "description": "Session client to ingest (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to ingest (default: 10)",
                    "default": 10,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore ingest cursor and rescan matching sessions",
                    "default": False,
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Session scope for global stores (default: project)",
                    "default": "project",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for cwd-scoped matching (default: current directory)",
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_ingest_sessions,
    },
    "prepare_session_distill": {
        "description": "One-shot project-scoped ingest plus recent observation packet for AI-led session-distill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "client": {
                    "type": "string",
                    "enum": ["auto", "claude-code", "codex", "codex-archive"],
                    "description": "Session client to ingest (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to ingest (default: 5)",
                    "default": 5,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore ingest cursor and rescan matching sessions",
                    "default": False,
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Session scope for global stores (default: project)",
                    "default": "project",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for cwd-scoped matching",
                },
                "observation_limit": {
                    "type": "integer",
                    "description": "Recent observations to include in the evidence packet (default: 5)",
                    "default": 5,
                },
                "max_chars_per_observation": {
                    "type": "integer",
                    "description": "Maximum raw_content chars per observation (default: 6000)",
                    "default": 6000,
                },
                "run_ingest": {
                    "type": "boolean",
                    "description": "Run ingest before building the packet (default: true)",
                    "default": True,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_prepare_session_distill,
    },
    "distill_sessions": {
        "description": "Run heuristic distill through MCP as a fallback to AI session-distill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Optional session ID"},
                "category": {
                    "type": "string",
                    "enum": ["architecture", "convention", "api", "bug", "decision"],
                    "description": "Optional memory category filter",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for Claude project session matching",
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_distill_sessions,
    },
    "list_candidates": {
        "description": "List structured memory candidates for human review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "accepted", "rejected"],
                    "description": "Candidate status to list (default: pending)",
                    "default": "pending",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum candidates to return across all candidate types (default: 100)",
                    "default": 100,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_list_candidates,
    },
    "auto_review_candidates": {
        "description": (
            "Run conservative heuristic auto-review across pending memory entries "
            "and rule candidates. Returns the summary shape from "
            "openspec/specs/mcp/spec.md (auto_confirmed / auto_rejected / "
            "kept_pending / needs_user_confirmation). Use apply=true to apply "
            "the decisions via the same status mutators users would invoke "
            "manually; apply=false (default) returns a preview without "
            "modifying any candidate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "apply": {
                    "type": "boolean",
                    "description": (
                        "When true, apply auto_confirm / auto_reject decisions. "
                        "When false (default), preview without writes."
                    ),
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_auto_review_candidates,
    },
    "suggest_supersede": {
        "description": "Suggest a supersede candidate to mark old truth historical.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "target_type": {
                    "type": "string",
                    "enum": ["memory_entry", "relation_fact", "confirmed_rule"],
                    "description": "Truth type to supersede",
                },
                "target_id": {"type": "string", "description": "Existing truth id to mark historical"},
                "replacement_type": {
                    "type": "string",
                    "enum": ["memory_entry", "relation_fact", "confirmed_rule"],
                    "description": "Replacement truth type",
                },
                "replacement_id": {"type": "string", "description": "Replacement truth id"},
                "reason": {"type": "string", "description": "Why the replacement is needed"},
                "evidence": {"type": "string", "description": "Evidence for the replacement"},
                "source": {"type": "string", "description": "Source id (optional)"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            },
            "required": ["project_name", "target_type", "target_id", "replacement_type", "replacement_id", "reason", "evidence"],
        },
        "handler": tool_suggest_supersede,
    },
    "confirm_supersede": {
        "description": "Confirm a supersede candidate and link truth records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Supersede candidate ID to confirm"},
            },
            "required": ["candidate_id"],
        },
        "handler": tool_confirm_supersede,
    },
    "reject_supersede": {
        "description": "Reject a supersede candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Supersede candidate ID to reject"},
            },
            "required": ["candidate_id"],
        },
        "handler": tool_reject_supersede,
    },
    "suggest_skill": {
        "description": "Suggest a procedural skill candidate for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "activation_condition": {"type": "string", "description": "When this workflow should run"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered workflow steps",
                },
                "termination_condition": {"type": "string", "description": "When this workflow is complete"},
                "success_examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Successful execution examples",
                },
                "source_session_id": {"type": "string", "description": "Source session id"},
                "source": {"type": "string", "description": "Source observation/file/candidate id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            },
            "required": ["project_name", "activation_condition", "steps", "termination_condition"],
        },
        "handler": tool_suggest_skill,
    },
    "confirm_skill": {
        "description": "Confirm a procedural skill candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Procedural candidate ID to confirm"},
            },
            "required": ["candidate_id"],
        },
        "handler": tool_confirm_skill,
    },
    "reject_skill": {
        "description": "Reject a procedural skill candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Procedural candidate ID to reject"},
            },
            "required": ["candidate_id"],
        },
        "handler": tool_reject_skill,
    },
    "record_skill_result": {
        "description": "Record one execution outcome for a confirmed skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Confirmed skill ID"},
                "success": {"type": "boolean", "description": "Whether the execution succeeded"},
            },
            "required": ["skill_id", "success"],
        },
        "handler": tool_record_skill_result,
    },
    "create_rule_candidate": {
        "description": "Create a rule candidate from a correction pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID where the correction occurred"},
                "pattern": {"type": "string", "description": "Rule pattern"},
                "trigger": {"type": "string", "description": "Trigger scenario"},
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Example instances (optional)",
                },
            },
            "required": ["project_name", "session_id", "pattern", "trigger"],
        },
        "handler": tool_create_rule_candidate,
    },
    "confirm_rule": {
        "description": "Promote a rule candidate to a confirmed rule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string", "description": "Rule candidate ID to confirm"},
            },
            "required": ["rule_id"],
        },
        "handler": tool_confirm_rule,
    },
    "reject_rule": {
        "description": "Reject a rule candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string", "description": "Rule candidate ID to reject"},
                "reason": {"type": "string", "description": "Reason for rejection (optional)"},
            },
            "required": ["rule_id"],
        },
        "handler": tool_reject_rule,
    },
    "suggest_rule": {
        "description": "Suggest a rule for later review (lighter than confirm_rule).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "pattern": {"type": "string", "description": "Rule pattern"},
                "trigger": {"type": "string", "description": "Trigger scenario"},
                "session_id": {"type": "string", "description": "Session ID (optional)"},
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Example instances (optional)",
                },
            },
            "required": ["project_name", "pattern", "trigger"],
        },
        "handler": tool_suggest_rule,
    },
    "suggest_memory_entry": {
        "description": "Suggest a memory entry (fact, decision, etc.) for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "category": {"type": "string", "enum": ["architecture", "convention", "api", "bug", "decision"]},
                "content": {"type": "string", "description": "Knowledge content"},
                "source": {"type": "string", "description": "Source observation id or session id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_name", "category", "content", "source"],
        },
        "handler": tool_suggest_memory_entry,
    },
    "confirm_memory_entry": {
        "description": "Confirm a pending memory entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "Memory entry ID to confirm"},
            },
            "required": ["entry_id"],
        },
        "handler": tool_confirm_memory_entry,
    },
    "reject_memory_entry": {
        "description": "Reject a pending memory entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "Memory entry ID to reject"},
            },
            "required": ["entry_id"],
        },
        "handler": tool_reject_memory_entry,
    },
    "suggest_relation_fact": {
        "description": "Suggest a typed relation between entities for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "source_entity": {"type": "string", "description": "Origin entity"},
                "target_entity": {"type": "string", "description": "Target entity"},
                "relation_type": {"type": "string", "description": "Relation type (e.g. depends_on)"},
                "evidence": {"type": "string", "description": "Evidence for this relation"},
                "source": {"type": "string", "description": "Source id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            },
            "required": ["project_name", "source_entity", "target_entity", "relation_type", "evidence", "source"],
        },
        "handler": tool_suggest_relation_fact,
    },
    "confirm_relation_fact": {
        "description": "Confirm a pending relation fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "Relation fact ID to confirm"},
            },
            "required": ["fact_id"],
        },
        "handler": tool_confirm_relation_fact,
    },
    "reject_relation_fact": {
        "description": "Reject a pending relation fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "Relation fact ID to reject"},
            },
            "required": ["fact_id"],
        },
        "handler": tool_reject_relation_fact,
    },
    "create_task_handoff": {
        "description": "Create a task handoff to record progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "task_id": {"type": "string", "description": "Task identifier"},
                "summary": {"type": "string", "description": "Progress summary"},
                "status": {"type": "string", "description": "Current status"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_name", "task_id", "summary", "status"],
        },
        "handler": tool_create_task_handoff,
    },
}


# =============================================================================
# JSON-RPC REQUEST HANDLER
# =============================================================================

SUPPORTED_PROTOCOL_VERSIONS = [
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
]


def handle_request(request: dict) -> dict | None:
    method = request.get("method") or ""
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "harness-mem", "version": _HARNESS_MEM_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method.startswith("notifications/"):
        # Notifications carry no id — per JSON-RPC spec they get no response
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": n,
                        "description": t["description"],
                        "inputSchema": t["input_schema"],
                    }
                    for n, t in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        # Whitelist arguments to declared schema properties
        import inspect

        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        try:
            handler = TOOLS[tool_name]["handler"]
            sig = inspect.signature(handler)
            accepts_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (ValueError, TypeError):
            accepts_var_keyword = False

        if not accepts_var_keyword:
            tool_args = {k: v for k, v in tool_args.items() if k in schema_props}

        # Coerce integer/float types per schema
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            try:
                if declared_type == "integer" and not isinstance(value, int):
                    tool_args[key] = int(value)
                elif declared_type == "number" and not isinstance(value, (int, float)):
                    tool_args[key] = float(value)
            except (ValueError, TypeError):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid value for parameter '{key}'"},
                }

        try:
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

    # Notifications (missing id) must never get a response
    if req_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


# =============================================================================
# STDOUT RESTORATION + MAIN LOOP
# =============================================================================


def _restore_stdout():
    """Restore real stdout for MCP JSON-RPC output."""
    global _REAL_STDOUT_FD
    if _REAL_STDOUT_FD is not None:
        try:
            os.dup2(_REAL_STDOUT_FD, 1)
        except OSError:
            pass
        finally:
            try:
                os.close(_REAL_STDOUT_FD)
            except OSError:
                pass
        _REAL_STDOUT_FD = None
    try:
        sys.stdout = os.fdopen(
            os.dup(1),
            "w",
            buffering=1,
            encoding=_REAL_STDOUT_ENCODING,
            errors=_REAL_STDOUT_ERRORS,
        )
    except OSError:
        sys.stdout = sys.__stdout__


def main():
    _restore_stdout()
    logger.info("harness-mem MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
