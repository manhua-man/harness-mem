"""Dogfooding — harness-mem uses itself to record project learnings.

This module records key development learnings and decisions
into the harness-mem memory system itself, so the project
can benefit from its own memory capabilities.
"""

from __future__ import annotations
from pathlib import Path

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.core.schemas import MemoryEntry


LEARNINGS_PROJECT = "harness-mem-self"


async def record_learning(
    category: str,
    content: str,
    source_session: str = "development",
    data_dir: Path | None = None,
) -> str:
    """Record a development learning as a MemoryEntry.

    Args:
        category: Memory category (architecture, convention, decision, etc.)
        content: What was learned
        source_session: Development session or PR reference
        data_dir: Optional data directory override

    Returns:
        The ID of the saved MemoryEntry.
    """
    backend = LocalMemoryBackend(data_dir or _default_data_dir())
    await backend.init()
    try:
        entry = MemoryEntry(
            project_name=LEARNINGS_PROJECT,
            category=category,
            content=content,
            confidence=0.95,
            source=f"dogfood:{source_session}",
            provenance={
                "session_id": source_session,
                "agent_type": "self",
                "observation_ids": [],
            },
        )
        entry_id = await backend.structured_store.save_memory_entry(entry)
        return entry_id
    finally:
        await backend.close()


async def record_decision(
    decision: str,
    rationale: str,
    alternatives: list[str] | None = None,
    source_session: str = "development",
    data_dir: Path | None = None,
) -> str:
    """Record an architectural or design decision.

    Args:
        decision: What was decided
        rationale: Why this was the right choice
        alternatives: What alternatives were considered
        source_session: Development session or PR reference

    Returns:
        The ID of the saved MemoryEntry.
    """
    content_parts = [f"Decision: {decision}", f"Rationale: {rationale}"]
    if alternatives:
        content_parts.append(f"Alternatives considered: {', '.join(alternatives)}")
    content = " | ".join(content_parts)

    return await record_learning(
        category="decision",
        content=content,
        source_session=source_session,
        data_dir=data_dir,
    )


async def record_convention(
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
    source_session: str = "development",
    data_dir: Path | None = None,
) -> str:
    """Record a coding convention or pattern.

    Args:
        pattern: The convention or pattern
        trigger: When this pattern applies
        examples: Concrete examples
        source_session: Development session or PR reference

    Returns:
        The ID of the saved ConfirmedRule (or MemoryEntry).
    """
    content_parts = [f"Convention: {pattern}", f"Trigger: {trigger}"]
    if examples:
        content_parts.append(f"Examples: {'; '.join(examples)}")
    content = " | ".join(content_parts)

    return await record_learning(
        category="convention",
        content=content,
        source_session=source_session,
        data_dir=data_dir,
    )


async def get_learnings(
    category: str | None = None,
    data_dir: Path | None = None,
) -> list[MemoryEntry]:
    """Retrieve recorded learnings.

    Args:
        category: Filter by category (optional)
        data_dir: Optional data directory override

    Returns:
        List of MemoryEntry objects.
    """
    backend = LocalMemoryBackend(data_dir or _default_data_dir())
    await backend.init()
    try:
        return await backend.structured_store.list_memory_entries(
            project_name=LEARNINGS_PROJECT,
            category=category,
            limit=100,
        )
    finally:
        await backend.close()


def _default_data_dir() -> Path:
    """Return the default data directory."""
    return Path.home() / ".harness-mem" / "data"


# Pre-seeded learnings for harness-mem itself
INITIAL_LEARNINGS = [
    {
        "category": "architecture",
        "content": "SQLite FTS5 provides sufficient search for local-first memory without external dependencies",
        "session": "initial-design",
    },
    {
        "category": "decision",
        "content": "Soft-delete with compacted flag over physical deletion preserves audit trail and enables undo",
        "session": "purge-design",
    },
    {
        "category": "convention",
        "content": "Phase/Next step/Why format provides actionable guidance without overwhelming users",
        "session": "ux-design",
    },
    {
        "category": "decision",
        "content": "MCP server as project-agnostic layer separates memory access from Claude Code internals",
        "session": "mcp-design",
    },
    {
        "category": "convention",
        "content": "Incremental ingest via cursor avoids re-processing already-ingested sessions",
        "session": "ingest-design",
    },
]


async def bootstrap_learnings(data_dir: Path | None = None) -> int:
    """Bootstrap initial learnings if none exist.

    Records the pre-seeded learnings above if the learnings
    project has no entries yet.

    Returns:
        Number of learnings recorded.
    """
    existing = await get_learnings(data_dir=data_dir)
    if existing:
        return 0

    recorded = 0
    for learning in INITIAL_LEARNINGS:
        await record_learning(
            category=learning["category"],
            content=learning["content"],
            source_session=learning["session"],
            data_dir=data_dir,
        )
        recorded += 1

    return recorded
