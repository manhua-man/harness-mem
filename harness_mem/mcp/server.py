#!/usr/bin/env python3
"""
harness-mem MCP Server — structured memory access for AI agents
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
  list_candidates       — pending/accepted/rejected review candidates
  auto_review_candidates — heuristic auto-confirm / auto-reject pass (preview or apply)
  suggest_correction    — one-shot rule replacement (new rule + supersede chain)
  create_rule_candidate — create a rule candidate
  confirm_rule          — promote candidate to confirmed rule

Future split note (do not split ad-hoc):
  This file currently sits at ~1550 lines / 33 tools after pulling out
  serializers (commit 0ec616d) and tool schemas (this commit). The
  remaining content is now mostly tool function bodies, the JSON-RPC
  handler, and stdio plumbing — readable as one file. The natural split
  axes for the next round are:

      mcp/
        server.py        — JSON-RPC handler, stdio plumbing, TOOLS factory
                           call, main loop. Stays small.
        backend.py       — _get_backend / set_backend_override singleton.
                           Public contract: set_backend_override is imported
                           by tests (tests/mcp/test_smoke.py,
                           tests/test_memory_type_search_payload.py,
                           tests/loop_harness/test_correction_supersede_one_shot.py)
                           — re-export from server.py if moved.
        serializers.py   — already extracted (0ec616d). Owns
                           _serialize_rule_candidate / _serialize_memory_
                           entry_candidate / _isoformat etc.
        tool_specs.py    — already extracted (this commit). Owns ToolSpec
                           typed dict + the schema registry. Handlers stay
                           in server.py and are passed in via build_tools.
        tools/
          read.py        — search_memory / timeline / trace_relations /
                           search_raw / search_skills / get_*
          ingest.py      — ingest_sessions / prepare_session_distill /
                           list_candidates / auto_review_candidates
          review.py      — confirm_* / reject_*
          suggest.py     — suggest_* / create_rule_candidate /
                           suggest_correction / create_task_handoff

  Reasons NOT to do the tools/ split today:
   1. set_backend_override is a public test-facing API; moving its module
      breaks imports across tests/. A re-export shim works but adds
      complexity without runtime benefit.
   2. _REAL_STDOUT_FD redirection lives at module-import time in this
      file. Splitting risks ordering bugs in stdio protection.
   3. No user-facing pain point drives the split — it's pure long-term
      maintainability. That class of change deserves an OpenSpec change
      proposal, not an ad-hoc refactor.

  When the file crosses ~2000 lines again, or when adding a new tool
  category forces a 5th cluster, file an OpenSpec change ("split MCP
  server into read/ingest/review/suggest modules") and execute it as a
  coordinated PR.
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
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, cast  # noqa: E402

from harness_mem import __version__ as _HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.commands.auto_review import auto_review_candidates  # noqa: E402
from harness_mem.commands.doctor import health_summary  # noqa: E402
from harness_mem.file_context import build_file_context  # noqa: E402
from harness_mem.commands.ingest import cmd_ingest  # noqa: E402
from harness_mem.commands.metabolism_pass import select_metabolism_pass  # noqa: E402
from harness_mem.commands.retrieval_signals import record_retrieval_signal  # noqa: E402
from harness_mem.commands.support import (  # noqa: E402
    SUPPORTED_INGEST_CLIENTS,
    get_active_project,
    normalize_client_name,
    resolve_ingest_client,
    set_active_project,
)
from harness_mem.commands.replay_window import (  # noqa: E402
    ReplayBudget,
    ReplayWindow,
    select_replay_window,
)
from harness_mem.commands.wake import cmd_wake_up  # noqa: E402
from harness_mem.core.schemas import (  # noqa: E402
    ProceduralCandidate,
    SkillPromotionCandidate,
    SkillRevisionSuggestionCandidate,
    SupersedeCandidate,
)
from harness_mem.core.schemas.metabolism_run import MetabolismRun  # noqa: E402
from harness_mem.core.schemas.project_profile import ProjectProfile  # noqa: E402
from harness_mem.core.schemas.skill_promotion_candidate import PromotionScope  # noqa: E402
from harness_mem.core.schemas.skill_revision_suggestion_candidate import (  # noqa: E402
    RevisionTrigger,
)
from harness_mem.knowledge_cache import (  # noqa: E402
    COMPACT_RENDERER_NAME,
    load_compact_wake_payload,
    render_compact_wake_payload,
)
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
from harness_mem.storage.local_structured_store import LocalStructuredStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("harness_mem_mcp")

DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"

_METABOLISM_PREVIEW_DOCTOR_POINTER = (
    "Run `harness-mem doctor` to inspect local data directory, "
    "signal store, and project context."
)

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
    include_shared: bool = False,
    shared_scope: str = "exclude",
) -> dict:
    """Search confirmed procedural skills."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}
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
        "curated_doc_paths": profile.curated_doc_paths,
    }


def tool_file_context(path: str, project_name: str | None = None) -> dict:
    """Return compact, source-attributed memory already associated with a path."""
    backend = _get_backend()
    try:
        result = asyncio.run(
            build_file_context(backend, project_name=project_name, path=path)
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    payload = result.to_dict()
    payload["success"] = True
    return payload


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


def tool_set_active_project(project_name: str) -> dict:
    """Set the active project so wake/search/suggest defaults pick it up.

    The active project is the implicit default for tools that take
    ``project_name`` and is the only thing that keeps memory written in
    different working directories from cross-contaminating.
    """
    name = (project_name or "").strip()
    if not name:
        return {"success": False, "error": "project_name must not be empty"}
    previous = get_active_project()
    set_active_project(name)
    return {
        "success": True,
        "project_name": name,
        "previous_active_project": previous,
    }


async def _merge_project_profile(
    project_name: str,
    *,
    description: str | None,
    stacks: list[str] | None,
    key_files: list[str] | None,
    curated_doc_paths: list[str] | None,
    conventions: list[str] | None,
    service_hints: list[str] | None,
    database_hints: list[str] | None,
    weak_link_signals: bool | None,
    replace: bool,
) -> ProjectProfile:
    """Apply a non-interactive update to ``ProjectProfile``.

    ``replace=False`` (default) merges: ``None`` keeps the existing value,
    a list extends with deduplication, and ``description`` overwrites only
    when explicitly provided. ``replace=True`` substitutes each provided
    field outright; missing fields still keep their existing values.
    """
    # Read DEFAULT_DATA_DIR through command_support so tests that
    # monkeypatch the data dir (tests/conftest.py:data_dir) flow through
    # this MCP tool too. Importing at call time is intentional.
    from harness_mem.commands import support as _support

    store = LocalProjectProfileStore(_support.DEFAULT_DATA_DIR)
    existing = await store.get(project_name)

    def _merge_list(old: list[str], new: list[str] | None) -> list[str]:
        if new is None:
            return list(old)
        if replace:
            return list(new)
        combined = list(old)
        seen = {item for item in combined}
        for item in new:
            if item not in seen:
                combined.append(item)
                seen.add(item)
        return combined

    if existing is None:
        profile = ProjectProfile(
            project_name=project_name,
            description=description or "",
            stacks=list(stacks or []),
            key_files=list(key_files or []),
            curated_doc_paths=list(curated_doc_paths or []),
            conventions=list(conventions or []),
            service_hints=list(service_hints or []),
            database_hints=list(database_hints or []),
            weak_link_signals=bool(weak_link_signals) if weak_link_signals is not None else False,
        )
    else:
        profile = ProjectProfile(
            id=existing.id,
            project_name=project_name,
            description=description if description is not None else existing.description,
            stacks=_merge_list(existing.stacks, stacks),
            key_files=_merge_list(existing.key_files, key_files),
            curated_doc_paths=_merge_list(existing.curated_doc_paths, curated_doc_paths),
            conventions=_merge_list(existing.conventions, conventions),
            service_hints=_merge_list(existing.service_hints, service_hints),
            database_hints=_merge_list(existing.database_hints, database_hints),
            weak_link_signals=(
                weak_link_signals if weak_link_signals is not None else existing.weak_link_signals
            ),
            created_at=existing.created_at,
            last_updated=datetime.now(timezone.utc),
            last_ingest_at=existing.last_ingest_at,
            last_ingest_session_id=existing.last_ingest_session_id,
        )

    await store.save(profile)
    return profile


def tool_update_project_profile(
    project_name: str,
    description: str | None = None,
    stacks: list[str] | None = None,
    key_files: list[str] | None = None,
    curated_doc_paths: list[str] | None = None,
    conventions: list[str] | None = None,
    service_hints: list[str] | None = None,
    database_hints: list[str] | None = None,
    weak_link_signals: bool | None = None,
    replace: bool = False,
) -> dict:
    """Non-interactive project profile update.

    Adds (or, with ``replace=True``, substitutes) profile fields. Fields
    omitted from the call are left untouched on the existing profile.
    Lists are deduplicated when merged so repeated calls are idempotent
    for the same value. Returns the resulting profile.
    """
    name = (project_name or "").strip()
    if not name:
        return {"success": False, "error": "project_name must not be empty"}

    profile = asyncio.run(
        _merge_project_profile(
            name,
            description=description,
            stacks=stacks,
            key_files=key_files,
            curated_doc_paths=curated_doc_paths,
            conventions=conventions,
            service_hints=service_hints,
            database_hints=database_hints,
            weak_link_signals=weak_link_signals,
            replace=replace,
        )
    )
    return {
        "success": True,
        "project_name": profile.project_name,
        "profile": {
            "description": profile.description,
            "stacks": profile.stacks,
            "key_files": profile.key_files,
            "curated_doc_paths": profile.curated_doc_paths,
            "conventions": profile.conventions,
            "service_hints": profile.service_hints,
            "database_hints": profile.database_hints,
            "weak_link_signals": profile.weak_link_signals,
            "last_updated": profile.last_updated.isoformat(),
        },
    }


def tool_wake(
    project_name: str | None = None,
    no_auto_ingest: bool = False,
    renderer: str = "default",
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
) -> dict:
    """Generate the wake-up context (project profile + recent rules / handoffs).

    Captures the printed wake-up summary as ``output`` so the agent can
    ingest it directly without spawning a CLI subprocess.
    """
    resolved = project_name or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }
    normalized_renderer = str(renderer or "default").strip().lower()
    if normalized_renderer not in {"default", COMPACT_RENDERER_NAME}:
        return {
            "success": False,
            "error": "renderer must be one of: default, compact",
        }
    if normalized_renderer == COMPACT_RENDERER_NAME:
        if include_skill_hints:
            return {
                "success": False,
                "project_name": resolved,
                "renderer": normalized_renderer,
                "error": "include_skill_hints is only supported with renderer=default",
            }
        backend = _get_backend()
        payload = load_compact_wake_payload(backend.data_dir, project_name=resolved)
        if payload is None:
            return {
                "success": False,
                "project_name": resolved,
                "renderer": normalized_renderer,
                "error": (
                    "compact wake is unavailable: generated wiki bridge artifacts "
                    "have not been built for this project"
                ),
            }
        return {
            "success": True,
            "project_name": resolved,
            "renderer": normalized_renderer,
            "output": render_compact_wake_payload(payload),
            "compact_payload": payload.to_dict(),
        }
    command_payload = _run_command_to_payload(
        cmd_wake_up(
            resolved,
            no_auto_ingest=no_auto_ingest,
            include_skill_hints=include_skill_hints,
            skill_hint_limit=skill_hint_limit,
        )
    )
    return {
        "project_name": resolved,
        "renderer": normalized_renderer,
        "include_skill_hints": include_skill_hints,
        "skill_hint_limit": skill_hint_limit,
        **command_payload,
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


def _replay_window_to_input_window(window: ReplayWindow) -> dict[str, Any]:
    """Serialize a ``ReplayWindow`` into the JSON-friendly preview shape.

    Locked in by ``test_metabolism_run_preview_shape_round_trip`` (3.5):
    ``time_range`` is an ISO ``{start, end}`` mapping, ``dimensions`` is
    a name → ``{selected_ids, truncated, total_seen}`` mapping in the
    selector's iteration order, ``signal_ids`` and ``notes`` are plain
    lists. Datetimes don't ``asdict`` cleanly, so we walk the dataclass
    by hand.
    """
    dimensions: dict[str, dict[str, Any]] = {}
    for name, dim in window.dimensions.items():
        dimensions[name] = {
            "selected_ids": list(dim.selected_ids),
            "truncated": dim.truncated,
            "total_seen": dim.total_seen,
        }
    return {
        "time_range": {
            "start": window.time_range[0].isoformat(),
            "end": window.time_range[1].isoformat(),
        },
        "dimensions": dimensions,
        "signal_ids": list(window.signal_ids),
        "notes": list(window.notes),
    }


def tool_metabolism_preview(
    project_name: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Preview the next metabolism run's input window.

    v2.3.0: read-only. Resolves the project (active-project fallback),
    normalizes the optional ``budget`` against ``ReplayBudget`` defaults,
    runs ``select_replay_window``, persists a
    ``MetabolismRun(kind="preview", status="preview")`` for audit, and
    returns the window summary. Selector / persistence failures funnel
    through a single ``except`` that records an
    ``MetabolismRun(status="error")`` (best-effort) and returns
    ``{success: False, error, doctor_pointer}``. This handler MUST NOT
    raise.
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }

    backend = _get_backend()
    started_at = datetime.now(timezone.utc)
    # Writers stay implementation-side per the StructuredStore Protocol
    # contract (only `list_metabolism_runs` is on the Protocol). Cast to
    # the local concrete store to access `save_metabolism_run`.
    structured_store = cast(LocalStructuredStore, backend.structured_store)

    try:
        budget_kwargs: dict[str, int] = {}
        if budget:
            for key in (
                "max_observations",
                "max_pending_candidates",
                "max_historical_truths",
                "max_low_success_skills",
                "max_repeat_search_hits",
                "max_total_tokens",
                "signal_lookback_days",
            ):
                if key in budget and budget[key] is not None:
                    budget_kwargs[key] = budget[key]

        normalized_budget = ReplayBudget(**budget_kwargs)
        window = asyncio.run(
            select_replay_window(
                backend,
                project_name=resolved,
                budget=normalized_budget,
            )
        )
        input_window = _replay_window_to_input_window(window)
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        run_id = asyncio.run(
            structured_store.save_metabolism_run(
                MetabolismRun(
                    project_name=resolved,
                    kind="preview",
                    status="preview",
                    started_at=started_at,
                    completed_at=completed_at,
                    input_window=input_window,
                    selected_signal_ids=list(window.signal_ids),
                    output_counts={"suggestions": 0},
                    duration_ms=duration_ms,
                    notes=list(window.notes) if window.notes else None,
                )
            )
        )
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        error_message = str(exc) or exc.__class__.__name__
        # Best-effort persist an error run record. Failure here is logged
        # and swallowed — the user-visible error payload is still returned.
        try:
            asyncio.run(
                structured_store.save_metabolism_run(
                    MetabolismRun(
                        project_name=resolved,
                        kind="preview",
                        status="error",
                        started_at=started_at,
                        completed_at=completed_at,
                        input_window={},
                        selected_signal_ids=[],
                        output_counts={"suggestions": 0},
                        duration_ms=duration_ms,
                        notes=[f"selector failed: {error_message}"],
                    )
                )
            )
        except Exception:
            logger.exception(
                "metabolism_preview: failed to persist error run for project=%s",
                resolved,
            )
        return {
            "success": False,
            "error": error_message,
            "doctor_pointer": _METABOLISM_PREVIEW_DOCTOR_POINTER,
        }

    return {
        "success": True,
        "run_id": run_id,
        "project_name": resolved,
        "time_range": input_window["time_range"],
        "dimensions": input_window["dimensions"],
        "notes": list(window.notes),
        "signals_used": len(window.signal_ids),
    }


def tool_metabolism_run(
    project_name: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Run a metabolism pass and persist suggestion candidates.

    v2.3.1: mirrors :func:`tool_metabolism_preview`'s argument shape and
    error handling but performs the full suggestion pass:

    1. Resolve the project (active-project fallback) and normalize
       ``budget`` against ``ReplayBudget`` defaults.
    2. Run :func:`select_metabolism_pass`, which wraps
       ``select_replay_window`` and produces merge / stale / supersede
       candidates (auto-supersede deferred to v2.3.2 — proposer
       returns ``[]``).
    3. Persist a ``MetabolismRun(kind="metabolism", status="completed")``
       audit record carrying per-type ``output_counts``.
    4. Persist each candidate, rewriting ``metabolism_run_id`` to the
       newly-saved run id (the pass writes a ``"pending"`` sentinel).

    On any exception the handler best-effort persists a
    ``MetabolismRun(kind="metabolism", status="error")`` and returns
    ``{success: False, error, doctor_pointer}`` without raising. This
    matches the v2.3.0 preview contract bit-for-bit so MCP callers can
    treat both tools the same way.
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }

    backend = _get_backend()
    started_at = datetime.now(timezone.utc)
    # Same Protocol-vs-impl reasoning as ``tool_metabolism_preview``:
    # writers stay implementation-side, so cast to the local concrete
    # store to access ``save_metabolism_run`` and the candidate writers.
    structured_store = cast(LocalStructuredStore, backend.structured_store)

    try:
        budget_kwargs: dict[str, int] = {}
        if budget:
            for key in (
                "max_observations",
                "max_pending_candidates",
                "max_historical_truths",
                "max_low_success_skills",
                "max_repeat_search_hits",
                "max_total_tokens",
                "signal_lookback_days",
            ):
                if key in budget and budget[key] is not None:
                    budget_kwargs[key] = budget[key]

        normalized_budget = ReplayBudget(**budget_kwargs)
        pass_result = asyncio.run(
            select_metabolism_pass(
                backend,
                project_name=resolved,
                budget=normalized_budget,
            )
        )
        window = pass_result.window
        input_window = _replay_window_to_input_window(window)

        merge_count = len(pass_result.merge)
        stale_count = len(pass_result.stale)
        supersede_count = len(pass_result.supersede)
        output_counts = {
            "merge_suggestions": merge_count,
            "stale_suggestions": stale_count,
            "supersede_suggestions": supersede_count,
        }

        # Window notes come from the replay-window selector; pass notes
        # come from the proposers (e.g. ``stale_scan_truncated``). Both
        # contribute to the run's audit trail.
        combined_notes: list[str] = []
        combined_notes.extend(window.notes)
        combined_notes.extend(pass_result.notes)

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        run_record = MetabolismRun(
            project_name=resolved,
            kind="metabolism",
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            input_window=input_window,
            selected_signal_ids=list(window.signal_ids),
            output_counts=output_counts,
            duration_ms=duration_ms,
            notes=combined_notes if combined_notes else None,
        )
        run_id = asyncio.run(structured_store.save_metabolism_run(run_record))

        # Persist candidates with the real run id. The pass writes a
        # ``"pending"`` sentinel so it stays free of the run lifecycle;
        # the MCP layer is the single place that knows the run id.
        for merge_candidate in pass_result.merge:
            merge_candidate.metabolism_run_id = run_id
            asyncio.run(
                structured_store.save_merge_suggestion_candidate(merge_candidate)
            )
        for stale_candidate in pass_result.stale:
            stale_candidate.metabolism_run_id = run_id
            asyncio.run(
                structured_store.save_stale_truth_suggestion_candidate(stale_candidate)
            )
        # Supersede candidates are deferred (proposer returns []) but
        # iterating still costs nothing and keeps the shape stable for
        # the day v2.3.2 reactivates the leg.
        for supersede in pass_result.supersede:
            asyncio.run(structured_store.save_supersede_candidate(supersede))
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        error_message = str(exc) or exc.__class__.__name__
        # Best-effort persist an error run record. Failure here is logged
        # and swallowed — the user-visible error payload is still returned.
        try:
            asyncio.run(
                structured_store.save_metabolism_run(
                    MetabolismRun(
                        project_name=resolved,
                        kind="metabolism",
                        status="error",
                        started_at=started_at,
                        completed_at=completed_at,
                        input_window={},
                        selected_signal_ids=[],
                        output_counts={
                            "merge_suggestions": 0,
                            "stale_suggestions": 0,
                            "supersede_suggestions": 0,
                        },
                        duration_ms=duration_ms,
                        notes=[f"metabolism_run failed: {error_message}"],
                    )
                )
            )
        except Exception:
            logger.exception(
                "metabolism_run: failed to persist error run for project=%s",
                resolved,
            )
        return {
            "success": False,
            "error": error_message,
            "doctor_pointer": _METABOLISM_PREVIEW_DOCTOR_POINTER,
        }

    return {
        "success": True,
        "run_id": run_id,
        "project_name": resolved,
        "time_range": input_window["time_range"],
        "dimensions": input_window["dimensions"],
        "notes": list(combined_notes),
        "signals_used": len(window.signal_ids),
        "output_counts": output_counts,
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
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, antigravity, opencode, hermes",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}

    payload = _run_command_to_payload(
        cmd_ingest(
            normalized_client,
            project_name,
            limit,
            full_rescan,
            scope=scope,
            project_root=project_root,
        )
    )
    return {
        "project_name": project_name,
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
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
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, antigravity, opencode, hermes",
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
            client=normalized_client,
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
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
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


# Pure serializers extracted to mcp/serializers.py — see the future-split
# note in the module docstring. We re-export the names here so internal
# callers (and any external import that already uses them) keep working.
from harness_mem.mcp.serializers import (  # noqa: E402, F401
    _isoformat,
    _serialize_merge_suggestion_candidate,
    _serialize_memory_entry_candidate,
    _serialize_procedural_candidate,
    _serialize_relation_fact_candidate,
    _serialize_rule_candidate,
    _serialize_skill_promotion_candidate,
    _serialize_skill_revision_suggestion_candidate,
    _serialize_stale_truth_suggestion_candidate,
    _serialize_supersede_candidate,
)


async def _gather_candidate_payload(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    status: str,
    limit: int,
) -> tuple[
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
]:
    rules = await backend.structured_store.list_rule_candidates(project_name, status=status)
    entries = await backend.structured_store.list_memory_entries(project_name, status=status, limit=limit)
    facts = await backend.structured_store.list_relation_facts(project_name, status=status, limit=limit)
    supersedes = await backend.structured_store.list_supersede_candidates(project_name, status=status)
    procedural = await backend.structured_store.list_procedural_candidates(project_name, status=status)
    skill_promotions = await backend.structured_store.list_skill_promotion_candidates(
        project_name, status=status
    )
    skill_revisions = await backend.structured_store.list_skill_revision_suggestion_candidates(
        project_name, status=status
    )
    merge_suggestions = await backend.structured_store.list_merge_suggestion_candidates(project_name, status=status)
    stale_suggestions = await backend.structured_store.list_stale_truth_suggestion_candidates(project_name, status=status)
    return (
        [_serialize_rule_candidate(candidate) for candidate in rules[:limit]],
        [_serialize_memory_entry_candidate(entry) for entry in entries],
        [_serialize_relation_fact_candidate(fact) for fact in facts],
        [_serialize_supersede_candidate(candidate) for candidate in supersedes[:limit]],
        [_serialize_procedural_candidate(candidate) for candidate in procedural[:limit]],
        [_serialize_skill_promotion_candidate(candidate) for candidate in skill_promotions[:limit]],
        [_serialize_skill_revision_suggestion_candidate(candidate) for candidate in skill_revisions[:limit]],
        [_serialize_merge_suggestion_candidate(candidate) for candidate in merge_suggestions[:limit]],
        [_serialize_stale_truth_suggestion_candidate(candidate) for candidate in stale_suggestions[:limit]],
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
        skill_promotion_candidates,
        skill_revision_suggestion_candidates,
        merge_suggestion_candidates,
        stale_truth_suggestion_candidates,
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
        *skill_promotion_candidates,
        *skill_revision_suggestion_candidates,
        *merge_suggestion_candidates,
        *stale_truth_suggestion_candidates,
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
        "skill_promotion_candidates": skill_promotion_candidates,
        "skill_revision_suggestion_candidates": skill_revision_suggestion_candidates,
        "merge_suggestion_candidates": merge_suggestion_candidates,
        "stale_truth_suggestion_candidates": stale_truth_suggestion_candidates,
        "count": len(candidates),
        "total_count": len(all_candidates),
        "rule_count": len(rule_candidates),
        "memory_entry_count": len(memory_entries),
        "relation_fact_count": len(relation_facts),
        "supersede_count": len(supersede_candidates),
        "procedural_count": len(procedural_candidates),
        "skill_promotion_count": len(skill_promotion_candidates),
        "skill_revision_suggestion_count": len(skill_revision_suggestion_candidates),
        "merge_suggestion_count": len(merge_suggestion_candidates),
        "stale_truth_suggestion_count": len(stale_truth_suggestion_candidates),
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
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
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


def tool_suggest_correction(
    project_name: str,
    supersedes_rule_id: str,
    pattern: str,
    trigger: str,
    reason: str,
    *,
    examples: list[str] | None = None,
    source_session_id: str = "",
) -> dict:
    """One-shot rule replacement: create new rule + mark old rule historical.

    This is the right tool to call when reality changed (Tauri v1 -> v2,
    framework upgrade, policy reversal) and an old confirmed rule is now
    actively wrong. The caller has already named the specific old rule, so
    no extra human confirm step is needed — the supersede chain is applied
    immediately.

    For brand-new rules (no specific old rule to replace), use
    ``create_rule_candidate`` -> ``confirm_rule`` instead.
    """
    backend = _get_backend()
    old_rule = asyncio.run(backend.structured_store.get_confirmed_rule(supersedes_rule_id))
    if old_rule is None:
        return {
            "success": False,
            "error": f"ConfirmedRule not found: {supersedes_rule_id}",
        }
    if old_rule.project_name != project_name:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} belongs to project "
                f"{old_rule.project_name!r}, not {project_name!r}"
            ),
        }
    if old_rule.valid_to is not None:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} is already historical "
                f"(valid_to={old_rule.valid_to.isoformat()})"
            ),
        }

    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    source_id = source_session_id or "agent-correction"
    new_rule = ConfirmedRule(
        id=str(uuid4()),
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        examples=list(examples or []),
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=f"correction:{source_id}",
        source_session_id=source_id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(new_rule))

    candidate = SupersedeCandidate(
        id=str(uuid4()),
        project_name=project_name,
        target_type="confirmed_rule",
        target_id=old_rule.id,
        replacement_type="confirmed_rule",
        replacement_id=new_rule.id,
        reason=reason,
        evidence=f"Agent-driven correction (source: {source_id}).",
        source=f"correction:{source_id}",
        confidence=1.0,
    )
    asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    confirmed = asyncio.run(
        backend.structured_store.confirm_supersede_candidate(candidate.id)
    )
    if confirmed is None:
        return {
            "success": False,
            "error": (
                f"Saved new rule {new_rule.id} but supersede confirmation failed; "
                f"old rule {old_rule.id} is still current. "
                f"Call confirm_supersede with candidate_id={candidate.id} to retry."
            ),
            "new_rule_id": new_rule.id,
            "supersede_candidate_id": candidate.id,
        }
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
    return {
        "success": True,
        "new_rule_id": new_rule.id,
        "old_rule_id": old_rule.id,
        "supersede_candidate_id": candidate.id,
        "old_rule_valid_to": confirmed.reviewed_at.isoformat() if confirmed.reviewed_at else None,
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


def tool_suggest_skill_promotion(
    skill_id: str,
    target_scope: str,
    portability_notes: str = "",
    disabled_assumptions: list[str] | None = None,
    confidence: float | None = None,
) -> dict:
    """Suggest promoting a project skill into shared scope."""
    if target_scope not in {"workspace", "global"}:
        return {
            "success": False,
            "error": "target_scope must be one of: workspace, global",
        }
    requested_scope = cast(PromotionScope, target_scope)

    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.get_skill(skill_id))
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    if skill.scope != "project":
        return {
            "success": False,
            "error": f"Only project-scoped skills can be promoted: {skill_id}",
        }

    candidate = SkillPromotionCandidate(
        project_name=skill.project_name,
        source_skill_id=skill.id,
        requested_scope=requested_scope,
        origin_project=skill.origin_project,
        source_ids=skill.source_ids,
        portability_notes=portability_notes,
        disabled_assumptions=disabled_assumptions or [],
        confidence=skill.confidence if confidence is None else confidence,
    )
    saved_id = asyncio.run(backend.structured_store.save_skill_promotion_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "skill_id": skill.id,
        "requested_scope": candidate.requested_scope,
        "status": candidate.status,
    }


def tool_confirm_skill_promotion(candidate_id: str) -> dict:
    """Confirm a skill promotion candidate into shared scope."""
    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.confirm_skill_promotion_candidate(candidate_id))
    if skill is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    return {
        "success": True,
        "candidate_id": candidate_id,
        "skill": serialize_skill(skill),
    }


def tool_reject_skill_promotion(candidate_id: str) -> dict:
    """Reject a skill promotion candidate."""
    backend = _get_backend()
    updated = asyncio.run(
        backend.structured_store.update_skill_promotion_candidate_status(
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
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=skill.project_name,
            signal_type=(
                "skill_result_success" if success else "skill_result_failure"
            ),
            target_kind="skill",
            target_id=skill.id,
            value=skill.success_rate,
        )
    )
    return {
        "success": True,
        "skill": serialize_skill(skill),
    }


def _skill_revision_summary(skill: Any, trigger: str) -> str:
    if trigger == "zero_success_after_repeated_use":
        return (
            f"Skill has 0 successes across {skill.usage_count} uses; "
            "review activation condition and steps against recent failures."
        )
    rate = 0.0 if skill.success_rate is None else skill.success_rate
    return (
        f"Skill success rate is {rate:.2f} across {skill.usage_count} uses; "
        "review the procedure against recent failure outcomes."
    )


def tool_detect_skill_improvements(
    project_name: str,
    limit: int = 20,
    lookback_days: int = 30,
) -> dict:
    """Create reviewed revision suggestions for low-success skills."""
    backend = _get_backend()
    effective_limit = max(1, min(int(limit), 200))
    effective_lookback_days = max(1, min(int(lookback_days), 365))

    async def _run() -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=effective_lookback_days)
        skills = await backend.structured_store.list_skills(project_name, status="active")
        pending = await backend.structured_store.list_skill_revision_suggestion_candidates(
            project_name,
            status="pending",
        )
        pending_skill_ids = {candidate.source_skill_id for candidate in pending}

        matched = [
            skill
            for skill in skills
            if (skill.success_rate is not None and skill.success_rate < 0.5)
            or (skill.usage_count >= 5 and skill.success_count == 0)
        ]
        matched.sort(
            key=lambda s: (
                s.success_rate is None,
                s.success_rate if s.success_rate is not None else 0.0,
                -s.usage_count,
            )
        )

        created: list[SkillRevisionSuggestionCandidate] = []
        skipped_existing = 0
        for skill in matched[:effective_limit]:
            if skill.id in pending_skill_ids:
                skipped_existing += 1
                continue
            failure_signals = await backend.structured_store.query_retrieval_signals(
                project_name,
                signal_type="skill_result_failure",
                target_kind="skill",
                target_id=skill.id,
                since=since,
                limit=1000,
            )
            success_signals = await backend.structured_store.query_retrieval_signals(
                project_name,
                signal_type="skill_result_success",
                target_kind="skill",
                target_id=skill.id,
                since=since,
                limit=1000,
            )
            trigger = cast(
                RevisionTrigger,
                (
                "zero_success_after_repeated_use"
                if skill.usage_count >= 5 and skill.success_count == 0
                else "low_success_rate"
                ),
            )
            candidate = SkillRevisionSuggestionCandidate(
                project_name=project_name,
                source_skill_id=skill.id,
                trigger=trigger,
                summary=_skill_revision_summary(skill, trigger),
                usage_count=skill.usage_count,
                success_count=skill.success_count,
                failure_count=skill.failure_count,
                success_rate=skill.success_rate,
                recent_failure_signal_ids=[signal.id for signal in failure_signals],
                recent_success_signal_ids=[signal.id for signal in success_signals],
                confidence=0.85 if trigger == "zero_success_after_repeated_use" else 0.7,
            )
            await backend.structured_store.save_skill_revision_suggestion_candidate(candidate)
            created.append(candidate)

        return {
            "success": True,
            "project_name": project_name,
            "lookback_days": effective_lookback_days,
            "matched_skill_count": len(matched),
            "created_count": len(created),
            "skipped_existing_count": skipped_existing,
            "candidate_ids": [candidate.id for candidate in created],
        }

    return asyncio.run(_run())


def tool_confirm_skill_revision(candidate_id: str) -> dict:
    """Accept a skill revision suggestion without rewriting the skill."""
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_skill_revision_suggestion_candidate(candidate_id)
    )
    if candidate is None or candidate.status != "pending":
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    updated = asyncio.run(
        backend.structured_store.update_skill_revision_suggestion_candidate_status(
            candidate_id,
            "accepted",
        )
    )
    if not updated:
        return {"success": False, "error": f"Failed to confirm candidate: {candidate_id}"}
    skill = asyncio.run(backend.structured_store.get_skill(candidate.source_skill_id))
    return {
        "success": True,
        "candidate_id": candidate_id,
        "status": "accepted",
        "skill": serialize_skill(skill) if skill is not None else None,
    }


def tool_reject_skill_revision(candidate_id: str) -> dict:
    """Reject a skill revision suggestion."""
    backend = _get_backend()
    updated = asyncio.run(
        backend.structured_store.update_skill_revision_suggestion_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
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
# REFLECTION JOB VISIBILITY (v2.4.0, Req 7)
# =============================================================================

# Mirrors the Literal sets on ReflectionJob so we can validate caller
# input without importing the schema at module-import time. Source of
# truth for the values is harness_mem.core.schemas.reflection_job.
_VALID_REFLECTION_JOB_STATUSES: frozenset[str] = frozenset(
    {"pending", "processing", "completed", "failed", "retryable", "needs_distill"}
)
_VALID_REFLECTION_JOB_KINDS: frozenset[str] = frozenset({"reflection"})

# Caller-facing limit window per Req 7.1 — default 50, hard ceiling 200.
_REFLECTION_JOB_LIST_DEFAULT_LIMIT = 50
_REFLECTION_JOB_LIST_MAX_LIMIT = 200


def tool_list_reflection_jobs(
    project_name: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = _REFLECTION_JOB_LIST_DEFAULT_LIMIT,
) -> dict:
    """List recent reflection jobs (Req 7.1, 7.3, 7.5, 7.6).

    Read-only filtered listing. Status / kind values outside the schema's
    Literal sets short-circuit with ``{success: false, error}`` listing
    the valid options (Req 7.5). The ``limit`` is clamped server-side to
    ``[1, 200]`` so a caller asking for ``limit=500`` still gets at most
    200 rows (Req 7.1).
    """
    if status is not None and status not in _VALID_REFLECTION_JOB_STATUSES:
        valid = ", ".join(sorted(_VALID_REFLECTION_JOB_STATUSES))
        return {
            "success": False,
            "error": f"Invalid status: {status!r}. Valid values: {valid}.",
        }
    if kind is not None and kind not in _VALID_REFLECTION_JOB_KINDS:
        valid = ", ".join(sorted(_VALID_REFLECTION_JOB_KINDS))
        return {
            "success": False,
            "error": f"Invalid kind: {kind!r}. Valid values: {valid}.",
        }

    # Clamp limit to [1, 200]. Anything non-int has already been coerced
    # by the JSON-RPC parameter handling layer; if it ever isn't, fall
    # back to the default rather than 500'ing.
    try:
        clamped = int(limit)
    except (TypeError, ValueError):
        clamped = _REFLECTION_JOB_LIST_DEFAULT_LIMIT
    clamped = max(1, min(clamped, _REFLECTION_JOB_LIST_MAX_LIMIT))

    backend = _get_backend()
    jobs = backend.reflection_job_store.list(
        project_name=project_name,
        status=status,
        kind=kind,
        limit=clamped,
    )
    return {
        "success": True,
        "jobs": [job.to_dict() for job in jobs],
    }


def tool_get_reflection_job(job_id: str) -> dict:
    """Fetch a single reflection job by id (Req 7.2, 7.4, 7.6).

    Read-only. Returns the full ``to_dict()`` payload on hit; on miss
    surfaces ``{success: false, error}`` with a "not found" message so
    Agents can branch on the result without parsing message text
    (Req 7.4).
    """
    backend = _get_backend()
    job = backend.reflection_job_store.get(job_id)
    if job is None:
        return {
            "success": False,
            "error": f"Reflection job not found: {job_id}",
        }
    return {
        "success": True,
        "job": job.to_dict(),
    }


def tool_health_summary(project_name: str | None = None) -> dict:
    """Read-only combined v2.4.0 + v2.4.2 project health summary (Req 6).

    Resolves the active project when ``project_name`` is omitted, then wraps
    the ``health_summary`` orchestrator's payload in the standard ``success``
    envelope. The orchestrator is total (never raises) and self-heals each
    failed category into a ``{"warnings": [...]}`` slice (Req 6.7), so this
    handler only needs to guard the project-resolution precondition. No
    ``print`` here per project rule P0 (MCP stdio protection).
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }
    backend = _get_backend()
    payload = asyncio.run(health_summary(backend, resolved))
    return {"success": True, "project_name": resolved, **payload}


# =============================================================================
# MCP TOOL REGISTRY
# =============================================================================

import asyncio  # noqa: E402 (moved here so the stdio redirect above is clean)

from harness_mem.mcp.tool_specs import ToolSpec, build_tools  # noqa: E402,F401

# The schema for each tool lives in ``tool_specs._SCHEMAS``. Handlers stay
# next to the backend singleton in this file. ``build_tools`` glues schemas
# and handlers together and validates that the two sets of keys match
# (so a typoed handler name fails at import time, not at request time).
TOOLS: dict[str, ToolSpec] = build_tools({
    "search_memory": tool_search_memory,
    "timeline": tool_timeline,
    "trace_relations": tool_trace_relations,
    "search_raw": tool_search_raw,
    "search_skills": tool_search_skills,
    "get_skill": tool_get_skill,
    "get_observations": tool_get_observations,
    "get_task_handoffs": tool_get_task_handoffs,
    "get_confirmed_rules": tool_get_confirmed_rules,
    "get_project_profile": tool_get_project_profile,
    "file_context": tool_file_context,
    "get_project_status": tool_get_project_status,
    "set_active_project": tool_set_active_project,
    "update_project_profile": tool_update_project_profile,
    "wake": tool_wake,
    "ingest_sessions": tool_ingest_sessions,
    "prepare_session_distill": tool_prepare_session_distill,
    "metabolism_preview": tool_metabolism_preview,
    "metabolism_run": tool_metabolism_run,
    "list_candidates": tool_list_candidates,
    "auto_review_candidates": tool_auto_review_candidates,
    "suggest_supersede": tool_suggest_supersede,
    "confirm_supersede": tool_confirm_supersede,
    "reject_supersede": tool_reject_supersede,
    "suggest_correction": tool_suggest_correction,
    "suggest_skill": tool_suggest_skill,
    "confirm_skill": tool_confirm_skill,
    "reject_skill": tool_reject_skill,
    "suggest_skill_promotion": tool_suggest_skill_promotion,
    "confirm_skill_promotion": tool_confirm_skill_promotion,
    "reject_skill_promotion": tool_reject_skill_promotion,
    "record_skill_result": tool_record_skill_result,
    "detect_skill_improvements": tool_detect_skill_improvements,
    "confirm_skill_revision": tool_confirm_skill_revision,
    "reject_skill_revision": tool_reject_skill_revision,
    "create_rule_candidate": tool_create_rule_candidate,
    "confirm_rule": tool_confirm_rule,
    "reject_rule": tool_reject_rule,
    "suggest_rule": tool_suggest_rule,
    "suggest_memory_entry": tool_suggest_memory_entry,
    "confirm_memory_entry": tool_confirm_memory_entry,
    "reject_memory_entry": tool_reject_memory_entry,
    "suggest_relation_fact": tool_suggest_relation_fact,
    "confirm_relation_fact": tool_confirm_relation_fact,
    "reject_relation_fact": tool_reject_relation_fact,
    "create_task_handoff": tool_create_task_handoff,
    "list_reflection_jobs": tool_list_reflection_jobs,
    "get_reflection_job": tool_get_reflection_job,
    "health_summary": tool_health_summary,
})


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
        except Exception as exc:
            # Full traceback to stderr for postmortem; concise class+message
            # surfaced to the client so an agent can debug without SSH-ing
            # to the MCP server's logs. We deliberately keep this short:
            # leaking the full traceback over JSON-RPC could expose
            # filesystem paths or third-party stack frames.
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Internal tool error in {tool_name}: {exc.__class__.__name__}: {exc}",
                },
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
