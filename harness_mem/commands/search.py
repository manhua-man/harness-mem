"""Search, timeline, and show command implementations."""

from __future__ import annotations

import sys

from harness_mem.commands.support import DEFAULT_DATA_DIR, log_command_invoked, resolve_project_name
from harness_mem.read_api import (
    format_observation_reference,
    format_search_score,
    format_validity_marker,
    parse_relative_time_window,
    preview_search_text,
    resolve_observation_identifier,
    search_header,
    search_memory,
    search_relation_facts,
    trace_relation_paths,
    timeline_observations,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})


async def cmd_search(
    project_name: str | None,
    query: str,
    mode: str = "auto",
    *,
    memory_type: list[str] | None = None,
    include_history: bool = False,
) -> int:
    """Search memory for a project.

    v1.6.1: ``memory_type`` accepts a list of {episodic, semantic, procedural}
    used as an OR filter on memory entries; observations are unaffected.
    """
    project_name = resolve_project_name(project_name, action_label="search")
    if not project_name:
        return 1

    if memory_type:
        normalized = [value.strip().lower() for value in memory_type if value]
        invalid = [value for value in normalized if value not in VALID_MEMORY_TYPES]
        if invalid:
            print(
                "Error: unknown memory_type: "
                + ", ".join(sorted(set(invalid)))
                + ". Valid: episodic | semantic | procedural.",
                file=sys.stderr,
            )
            return 1
        memory_type = normalized
    else:
        memory_type = None

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        print(f"# Search: {query}")
        parsed_time = parse_relative_time_window(query)
        effective_query = parsed_time.query
        if parsed_time.time_window:
            start, end = parsed_time.time_window
            print(
                "Time window: "
                f"{start.isoformat() if start else '*'} -> {end.isoformat() if end else '*'}"
            )
        print()

        entries, observations = await search_memory(
            backend,
            project_name=project_name,
            query=effective_query,
            scope="project",
            mode=mode,
            memory_entry_limit=10,
            observation_limit=10,
            memory_type=memory_type,
            include_history=include_history,
            time_window=parsed_time.time_window,
        )
        relation_facts = await search_relation_facts(
            backend,
            project_name=project_name,
            query=effective_query,
            scope="project",
            limit=10,
            include_history=include_history,
            time_window=parsed_time.time_window,
        )
        combined_results = entries or relation_facts or observations
        print(search_header(combined_results, mode))
        print()

        if entries:
            print(f"## Memory Entries ({len(entries)} results)")
            for entry in entries:
                preview = entry.content[:150] + "..." if len(entry.content) > 150 else entry.content
                search_mode = getattr(entry, "_search_mode", mode)
                entry_memory_type = getattr(entry, "memory_type", "semantic")
                print(
                    f"- [{entry.category}/{entry_memory_type}]{format_validity_marker(entry)} {preview}  "
                    f"(score: {format_search_score(entry)}, mode: {search_mode})  -> structured"
                )
                await backend.structured_store.touch_memory_entry(entry.id)
            print()

        if relation_facts:
            print(f"## Relation Facts ({len(relation_facts)} results)")
            for fact in relation_facts:
                evidence = fact.evidence[:150] + "..." if len(fact.evidence) > 150 else fact.evidence
                print(
                    f"- {fact.source_entity} --{fact.relation_type}-> {fact.target_entity}"
                    f"{format_validity_marker(fact)}: "
                    f"{evidence}  "
                    f"(confidence: {fact.confidence:.2f}, score: {format_search_score(fact)}, mode: fts)  "
                    "-> relation"
                )
            print()

        if observations:
            print(f"## Observations ({len(observations)} results)")
            for observation in observations:
                preview = preview_search_text(observation.raw_content, effective_query)
                search_mode = getattr(observation, "_search_mode", mode)
                print(
                    f"- {format_observation_reference(observation)} {preview}  "
                    f"(score: {format_search_score(observation)}, mode: {search_mode})  -> verbatim"
                )
            print()

        log_command_invoked(
            "search",
            project_name=project_name,
            extra={
                "query": query,
                "effective_query": effective_query,
                "requested_mode": mode,
                "memory_entry_count": len(entries),
                "relation_fact_count": len(relation_facts),
                "observation_count": len(observations),
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
            },
        )
    finally:
        await backend.close()
    return 0


async def cmd_trace_relations(
    project_name: str | None,
    source_entity: str,
    *,
    relation_type: str | None = None,
    max_depth: int = 2,
    limit: int = 10,
    min_confidence: float = 0.0,
    include_history: bool = False,
) -> int:
    """Trace bounded relation paths for a project entity."""
    project_name = resolve_project_name(project_name, action_label="trace-relations")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        try:
            paths = await trace_relation_paths(
                backend,
                project_name=project_name,
                source_entity=source_entity,
                relation_type=relation_type,
                max_depth=max_depth,
                limit=limit,
                min_confidence=min_confidence,
                include_history=include_history,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(f"# Relation Trace: {source_entity}")
        print(f"Project: {project_name}")
        print(f"Max depth: {max_depth}")
        if relation_type:
            print(f"Relation type: {relation_type}")
        print()

        if not paths:
            print("No relation paths found.")
            return 0

        for index, path in enumerate(paths, 1):
            chain = " -> ".join(path.entities)
            print(f"## Path {index} (depth={path.depth}, confidence={path.confidence:.2f})")
            print(chain)
            for fact in path.facts:
                evidence = fact.evidence[:160] + "..." if len(fact.evidence) > 160 else fact.evidence
                print(
                    f"- {fact.source_entity} --{fact.relation_type}-> {fact.target_entity}"
                    f"{format_validity_marker(fact)}: {evidence}"
                )
            print()

        log_command_invoked(
            "trace-relations",
            project_name=project_name,
            extra={
                "source_entity": source_entity,
                "relation_type": relation_type,
                "max_depth": max_depth,
                "limit": limit,
                "path_count": len(paths),
                "include_history": include_history,
            },
        )
    finally:
        await backend.close()
    return 0


async def cmd_timeline(project_name: str | None, limit: int = 50) -> int:
    """Show timeline of observations."""
    project_name = resolve_project_name(project_name, action_label="timeline")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        observations = await timeline_observations(backend, project_name=project_name, limit=limit)
        print(f"# Timeline ({len(observations)} observations)")
        for observation in observations:
            timestamp = observation.timestamp.strftime("%Y-%m-%d %H:%M") if observation.timestamp else "?"
            preview = observation.raw_content[:100].replace("\n", " ")
            print(f"- {timestamp} {format_observation_reference(observation)} {preview}")
        print()
    finally:
        await backend.close()
    return 0


async def cmd_show(project_name: str | None, observation_id: str) -> int:
    """Show a specific observation."""
    resolved_project = (
        resolve_project_name(project_name, required=False, action_label="show") if project_name else None
    )
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        observation, resolution_error = await resolve_observation_identifier(
            backend,
            observation_id,
            project_name=resolved_project,
        )
        if resolution_error:
            print(resolution_error)
            return 1
        if not observation:
            print(f"Observation not found: {observation_id}")
            return 1
        if resolved_project and observation.metadata.get("project_name") != resolved_project:
            print(f"Observation {observation.id} does not belong to project: {resolved_project}")
            return 1

        print(f"# Observation: {observation.id}")
        print(f"Session: {observation.session_id}")
        print(f"Client: {observation.client}")
        print(f"Type: {observation.content_type}")
        print(f"Timestamp: {observation.timestamp}")
        print(f"Tags: {', '.join(observation.tags)}")
        if observation.metadata.get("provenance"):
            print(f"Provenance: {observation.metadata['provenance']}")
        print()
        print(observation.raw_content)
    finally:
        await backend.close()
    return 0
