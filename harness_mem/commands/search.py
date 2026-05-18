"""Search, timeline, and show command implementations."""

from __future__ import annotations

from harness_mem.commands.support import DEFAULT_DATA_DIR, log_command_invoked, resolve_project_name
from harness_mem.read_api import (
    format_observation_reference,
    format_search_score,
    preview_search_text,
    resolve_observation_identifier,
    search_header,
    search_memory,
    search_relation_facts,
    timeline_observations,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def cmd_search(
    project_name: str | None,
    query: str,
    mode: str = "auto",
) -> int:
    """Search memory for a project."""
    project_name = resolve_project_name(project_name, action_label="search")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        print(f"# Search: {query}")
        print()

        entries, observations = await search_memory(
            backend,
            project_name=project_name,
            query=query,
            scope="project",
            mode=mode,
            memory_entry_limit=10,
            observation_limit=10,
        )
        relation_facts = await search_relation_facts(
            backend,
            project_name=project_name,
            query=query,
            scope="project",
            limit=10,
        )
        combined_results = entries or relation_facts or observations
        print(search_header(combined_results, mode))
        print()

        if entries:
            print(f"## Memory Entries ({len(entries)} results)")
            for entry in entries:
                preview = entry.content[:150] + "..." if len(entry.content) > 150 else entry.content
                search_mode = getattr(entry, "_search_mode", mode)
                memory_type = getattr(entry, "memory_type", "semantic")
                print(
                    f"- [{entry.category}/{memory_type}] {preview}  "
                    f"(score: {format_search_score(entry)}, mode: {search_mode})  -> structured"
                )
                await backend.structured_store.touch_memory_entry(entry.id)
            print()

        if relation_facts:
            print(f"## Relation Facts ({len(relation_facts)} results)")
            for fact in relation_facts:
                evidence = fact.evidence[:150] + "..." if len(fact.evidence) > 150 else fact.evidence
                print(
                    f"- {fact.source_entity} --{fact.relation_type}-> {fact.target_entity}: "
                    f"{evidence}  "
                    f"(confidence: {fact.confidence:.2f}, score: {format_search_score(fact)}, mode: fts)  "
                    "-> relation"
                )
            print()

        if observations:
            print(f"## Observations ({len(observations)} results)")
            for observation in observations:
                preview = preview_search_text(observation.raw_content, query)
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
                "requested_mode": mode,
                "memory_entry_count": len(entries),
                "relation_fact_count": len(relation_facts),
                "observation_count": len(observations),
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
