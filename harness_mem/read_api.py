"""Shared read-path helpers used by CLI commands and the MCP server."""

from __future__ import annotations

from typing import Any, Sequence

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def search_memory(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    mode: str = "auto",
    memory_entry_limit: int = 20,
    observation_limit: int = 20,
) -> tuple[list[MemoryEntry], list[Observation]]:
    """Return structured and verbatim search results with shared filtering."""
    if scope == "all":
        entries = await backend.structured_store.search_memory_entries(
            query,
            project_name=None,
            limit=memory_entry_limit,
            mode=mode,
        )
        observations = await backend.verbatim_store.search(
            query,
            limit=observation_limit,
            mode=mode,
        )
        return entries, observations

    entries = await backend.structured_store.search_memory_entries(
        query,
        project_name,
        limit=memory_entry_limit,
        mode=mode,
    )
    observations = await backend.verbatim_store.search(
        query,
        project_name=project_name,
        limit=observation_limit,
        mode=mode,
    )
    return entries, observations


async def search_relation_facts(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    limit: int = 10,
) -> list[RelationFact]:
    """Return relation facts matching the query with shared project scoping."""
    if scope == "all":
        return await backend.structured_store.search_relation_facts(
            query,
            project_name=None,
            limit=limit,
        )

    return await backend.structured_store.search_relation_facts(
        query,
        project_name=project_name,
        limit=limit,
    )


async def timeline_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int = 50,
) -> list[Observation]:
    """Return a project-scoped observation timeline."""
    return await backend.verbatim_store.timeline(project_name=project_name, limit=limit)


async def resolve_observation_identifier(
    backend: LocalMemoryBackend,
    identifier: str,
    *,
    project_name: str | None = None,
) -> tuple[Observation | None, str | None]:
    """Resolve either an observation id or a unique session id."""
    observation = await backend.verbatim_store.get(identifier)
    if observation is not None:
        return observation, None

    session_matches = await backend.verbatim_store.list(session_id=identifier, limit=100)
    if project_name:
        session_matches = [
            match for match in session_matches if match.metadata.get("project_name") == project_name
        ]

    if len(session_matches) == 1:
        return session_matches[0], None

    if len(session_matches) > 1:
        choices = ", ".join(match.id for match in session_matches[:5])
        more = "" if len(session_matches) <= 5 else f", ... (+{len(session_matches) - 5} more)"
        return (
            None,
            f"Multiple observations found for session: {identifier}. Use one of these observation ids: {choices}{more}",
        )

    return None, None


async def build_search_project_context_map(
    backend: LocalMemoryBackend,
    *,
    entries: Sequence[MemoryEntry] = (),
    observations: Sequence[Observation] = (),
    relation_facts: Sequence[RelationFact] = (),
) -> dict[str, list[str]]:
    """Resolve project profile stacks for search results."""
    project_names = {
        entry.project_name
        for entry in entries
        if entry.project_name
    }
    project_names.update(
        str(observation.metadata["project_name"])
        for observation in observations
        if isinstance(observation.metadata.get("project_name"), str)
    )
    project_names.update(
        fact.project_name
        for fact in relation_facts
        if fact.project_name
    )
    project_names.discard(None)
    if not project_names:
        return {}

    store = LocalProjectProfileStore(backend.data_dir)
    tech_stack_by_project: dict[str, list[str]] = {}
    for project_name in sorted(project_names):
        if not project_name:
            continue
        profile = await store.get(project_name)
        tech_stack_by_project[project_name] = list(profile.stacks) if profile else []
    return tech_stack_by_project


def search_header(results: Sequence[object], requested_mode: str) -> str:
    """Format a stable search header based on the effective search mode."""
    if not results:
        return f"[{requested_mode.upper()} Search]"
    first = results[0]
    effective_mode = getattr(first, "_search_mode", requested_mode)
    fallback_reason = getattr(first, "_search_fallback_reason", None)
    if effective_mode == "hybrid":
        return "[Hybrid Search]"
    if fallback_reason:
        return f"[FTS Search] ({fallback_reason}, using full-text search)"
    return "[FTS Search]"


def format_search_score(result: object) -> str:
    """Return the best available score field for display."""
    score = getattr(result, "_score", None)
    if score is None:
        score = getattr(result, "_hybrid_score", None)
    if score is None:
        score = getattr(result, "_fts_score", None)
    if isinstance(score, (int, float)):
        return f"{score:.3f}"
    return "n/a"


def format_observation_reference(observation: Observation) -> str:
    """Show the observation id that can be passed back into `show`."""
    return f"[{observation.id}] session: {observation.session_id}"


def preview_search_text(text: str, query: str, *, max_chars: int = 200) -> str:
    """Return a compact preview centered near the first query match."""
    cleaned_query = query.strip()
    candidates = [cleaned_query, *cleaned_query.split()]
    lowered = text.lower()
    match_index = -1
    for candidate in sorted({c for c in candidates if c}, key=len, reverse=True):
        match_index = lowered.find(candidate.lower())
        if match_index >= 0:
            break

    if match_index < 0:
        preview = text[:max_chars]
        if len(text) > max_chars:
            preview += "..."
        return preview.replace("\n", " ")

    context_before = max_chars // 3
    start = max(0, match_index - context_before)
    end = min(len(text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)

    preview = text[start:end].replace("\n", " ")
    if start > 0:
        preview = "..." + preview
    if end < len(text):
        preview += "..."
    return preview


def serialize_memory_entry_search_result(
    entry: object,
    requested_mode: str,
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize a structured memory result for MCP responses."""
    project_name = getattr(entry, "project_name", None)
    return {
        "id": getattr(entry, "id"),
        "project_name": project_name,
        "tech_stack": _tech_stack_for_project(project_name, tech_stack_by_project),
        "category": getattr(entry, "category"),
        "content": getattr(entry, "content"),
        "confidence": getattr(entry, "confidence"),
        "tags": getattr(entry, "tags"),
        "provenance": getattr(entry, "provenance"),
        "search_mode": getattr(entry, "_search_mode", requested_mode),
        "score": _raw_search_score(entry),
    }


def serialize_observation_search_result(
    observation: Observation,
    requested_mode: str,
    query: str = "",
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize an observation search result for MCP responses."""
    project_name = observation.metadata.get("project_name")
    return {
        "id": observation.id,
        "project_name": project_name,
        "tech_stack": _tech_stack_for_project(project_name, tech_stack_by_project),
        "session_id": observation.session_id,
        "content_type": observation.content_type,
        "preview": preview_search_text(observation.raw_content, query, max_chars=200),
        "search_mode": getattr(observation, "_search_mode", requested_mode),
        "score": _raw_search_score(observation),
    }


def serialize_relation_fact_search_result(
    fact: RelationFact,
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize a relation fact search result for MCP responses."""
    return {
        "id": fact.id,
        "project_name": fact.project_name,
        "tech_stack": _tech_stack_for_project(fact.project_name, tech_stack_by_project),
        "source_entity": fact.source_entity,
        "target_entity": fact.target_entity,
        "relation_type": fact.relation_type,
        "confidence": fact.confidence,
        "evidence": fact.evidence,
        "source": fact.source,
        "tags": fact.tags,
        "provenance": fact.provenance,
        "search_mode": "fts",
        "score": _raw_search_score(fact),
    }


def serialize_timeline_observation(observation: Observation) -> dict[str, Any]:
    """Serialize a timeline item for MCP responses."""
    return {
        "id": observation.id,
        "session_id": observation.session_id,
        "client": observation.client,
        "content_type": observation.content_type,
        "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
        "preview": observation.raw_content[:150].replace("\n", " "),
        "tags": observation.tags,
    }


def serialize_observation(observation: Observation) -> dict[str, Any]:
    """Serialize a full observation payload."""
    return {
        "id": observation.id,
        "session_id": observation.session_id,
        "client": observation.client,
        "content_type": observation.content_type,
        "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
        "raw_content": observation.raw_content,
        "tags": observation.tags,
        "metadata": observation.metadata,
    }


def _raw_search_score(result: object) -> float | None:
    score = getattr(result, "_score", None)
    if score is None:
        score = getattr(result, "_hybrid_score", None)
    if score is None:
        score = getattr(result, "_fts_score", None)
    return score if isinstance(score, (int, float)) else None


def _tech_stack_for_project(
    project_name: object,
    tech_stack_by_project: dict[str, list[str]] | None,
) -> list[str]:
    if not isinstance(project_name, str) or not tech_stack_by_project:
        return []
    return list(tech_stack_by_project.get(project_name, []))
