"""Distill command implementation."""

from __future__ import annotations

from pathlib import Path

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.commands.ingest import _list_claude_sessions_for_current_project
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_cli_event,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.event_log import EventType
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def cmd_distill(
    project_name: str | None,
    session_id: str | None = None,
    category: str | None = None,
    project_root: str | None = None,
) -> int:
    """Extract structured memory and explicit relation facts from sessions."""
    project_name = resolve_project_name(project_name, action_label="distill")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        adapter = ClaudeCodeAdapter(backend)
        resolved_project_root = _resolve_distill_project_root(project_root)
        session_project_name, sessions = _list_claude_sessions_for_current_project(
            adapter,
            project_name=project_name,
            project_root=resolved_project_root,
        )

        if session_id:
            entries = await adapter.distill_session(
                session_id,
                project_name,
                category=category,
                session_project_name=session_project_name,
            )
            relation_facts = [] if category else await adapter.distill_relation_facts(
                session_id,
                project_name,
                session_project_name=session_project_name,
            )
            if entries or relation_facts:
                print(f"Extracted {len(entries)} memory entries from {session_id}:")
                for entry in entries:
                    source_label = _memory_entry_source_label(entry)
                    print(f"  [{entry.category}] {entry.content[:100]}  (source: {source_label})")
                if relation_facts:
                    print(f"Extracted {len(relation_facts)} relation facts from {session_id}:")
                    for fact in relation_facts:
                        print(
                            f"  {fact.source_entity} --{fact.relation_type}-> "
                            f"{fact.target_entity}  (source: {fact.source})"
                        )
                _log_distill_events(
                    project_name=project_name,
                    session_id=session_id,
                    category=category,
                    memory_entries=len(entries),
                    relation_facts=len(relation_facts),
                )
                return 0

            if category:
                print(f"No {category} entries found in session {session_id}")
                return 1
            print(f"No patterns found in session {session_id}")
            _log_distill_events(
                project_name=project_name,
                session_id=session_id,
                category=category,
                memory_entries=0,
                relation_facts=0,
            )
            return 0

        if not sessions:
            print(f"No sessions found for project: {project_name}")
            return 1

        cat_suffix = f" ({category})" if category else ""
        print(f"Distilling {len(sessions)} sessions for {project_name}{cat_suffix}...")
        if session_project_name != project_name:
            print(f"Claude session project: {session_project_name}")
        total = 0
        relation_total = 0
        for session in sessions:
            current_session_id = str(session["session_id"])
            entries = await adapter.distill_session(
                current_session_id,
                project_name,
                category=category,
                session_project_name=session_project_name,
            )
            for entry in entries:
                source_label = _memory_entry_source_label(entry)
                print(f"  [{entry.category}] {entry.content[:100]}  (source: {source_label})")
                total += 1
            if not category:
                relation_facts = await adapter.distill_relation_facts(
                    current_session_id,
                    project_name,
                    session_project_name=session_project_name,
                )
                for fact in relation_facts:
                    print(
                        f"  [relation] {fact.source_entity} --{fact.relation_type}-> "
                        f"{fact.target_entity}  (source: {fact.source})"
                    )
                    relation_total += 1

        if total == 0 and category:
            print(f"No {category} entries found across {len(sessions)} sessions")
            return 1
        if total == 0 and relation_total == 0:
            print(f"No patterns found across {len(sessions)} sessions")
            _log_distill_events(
                project_name=project_name,
                session_id=None,
                category=category,
                memory_entries=0,
                relation_facts=0,
                sessions=len(sessions),
            )
            return 0

        print(f"Extracted {total} memory entries from {len(sessions)} sessions")
        if relation_total:
            print(f"Extracted {relation_total} relation facts from {len(sessions)} sessions")
        _log_distill_events(
            project_name=project_name,
            session_id=None,
            category=category,
            memory_entries=total,
            relation_facts=relation_total,
            sessions=len(sessions),
        )
        return 0
    finally:
        await backend.close()


def _resolve_distill_project_root(project_root: str | None) -> Path:
    if project_root:
        return normalize_project_root(Path(project_root).expanduser())
    return normalize_project_root(Path.cwd())


def _memory_entry_source_label(entry: object) -> str:
    for tag in getattr(entry, "tags", []) or []:
        if tag.startswith("pattern-source:"):
            return tag.split(":", 1)[1]
    return str(getattr(entry, "category", "unknown"))


def _log_distill_events(
    *,
    project_name: str,
    session_id: str | None,
    category: str | None,
    memory_entries: int,
    relation_facts: int,
    sessions: int | None = None,
) -> None:
    extra = {
        "category": category,
        "memory_entries": memory_entries,
        "relation_facts": relation_facts,
    }
    if sessions is not None:
        extra["sessions"] = sessions
    log_command_invoked(
        "distill",
        project_name=project_name,
        session_id=session_id,
        extra=extra,
    )
    log_cli_event(
        EventType.MEMORY_DISTILLED,
        project_name=project_name,
        command="distill",
        session_id=session_id,
        extra=extra,
    )
