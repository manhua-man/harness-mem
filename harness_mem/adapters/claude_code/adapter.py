"""Claude Code adapter — ingest Claude Code sessions into harness-mem."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import (
    extract_relation_facts,
    extract_heuristic_entries,
    list_session_files,
    parse_claude_jsonl_session,
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.schemas import MemoryEntry, Observation, RelationFact
from harness_mem.core.interfaces.memory_backend import MemoryBackend


# Default Claude Code session directory
DEFAULT_SESSIONS_DIR = Path.home() / ".claude" / "projects"


class ClaudeCodeAdapter:
    """Adapter for ingesting Claude Code sessions.

    Reads .jsonl session files from ~/.claude/projects/{project_name}/
    and converts them to Observations + MemoryEntries.
    """

    def __init__(self, backend: MemoryBackend | None, sessions_dir: Path | None = None):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR

    def list_project_sessions(
        self,
        project_name: str,
        min_size_kb: int = 100,
        limit: int | None = None,
    ) -> list[SessionRecord]:
        """List session files for a project."""
        project_dir = self.sessions_dir / project_name
        if not project_dir.exists():
            return []
        sessions = list_session_files(project_dir, min_size_kb=min_size_kb, pattern="*.jsonl")
        if limit is not None:
            return sessions[:limit]
        return sessions

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 100,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """Return normalized session metadata through the shared adapter contract."""
        del issues
        if not project_name:
            return []
        return self.list_project_sessions(project_name, min_size_kb=min_size_kb, limit=limit)

    def parse_jsonl_session(self, session_path: Path) -> list[dict[str, Any]]:
        """Parse a Claude Code .jsonl session file into turns."""
        return parse_claude_jsonl_session(session_path, on_error="silent")

    def turns_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
    ) -> Observation:
        """Convert parsed session to a single Observation."""
        turns = self.parse_jsonl_session(session_path)

        # Summarize turns into a readable transcript
        lines = [f"# Session: {session_id}"]
        display_turns = self._select_observation_turns(turns, max_turns=20)
        for i, turn in display_turns:
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for resp in turn["assistant"][:2]:
                    lines.append(f"\nAssistant: {resp[:500]}")
            if turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"][:5]]
                lines.append(f"\nTools: {', '.join(tool_names)}")
            if i == 10 and len(turns) > 20:
                omitted = len(turns) - 20
                lines.append(f"\n[... {omitted} middle turns omitted ...]")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="claude-code",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata={"project_name": project_name},
            tags=["session", "claude-code"],
        )

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        """Bridge the shared adapter contract to the Claude-specific implementation."""
        del issues
        if not project_name:
            raise ValueError("project_name is required for Claude Code observations")
        return self.turns_to_observation(session_path, session_id, project_name)

    async def ingest_project(
        self,
        project_name: str,
        limit: int = 10,
        min_size_kb: int = 100,
    ) -> dict:
        """Ingest recent sessions for a project.

        Returns dict with counts of ingested observations.
        """
        sessions = self.list_project_sessions(project_name, min_size_kb)
        sessions = sessions[:limit]

        ingested = 0
        errors = 0
        if self.backend is None:
            raise RuntimeError("ClaudeCodeAdapter.ingest requires an initialized backend")

        for session in sessions:
            try:
                session_id = session["session_id"]
                obs = self.turns_to_observation(session["path"], session_id, project_name)
                await self.backend.verbatim_store.save(obs)
                ingested += 1
            except Exception:
                errors += 1

        return {
            "project_name": project_name,
            "sessions_found": len(self.list_project_sessions(project_name, 0)),
            "ingested": ingested,
            "errors": errors,
        }

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 100,
    ) -> dict[str, Any]:
        """Shared adapter contract wrapper for project-scoped Claude ingestion."""
        if not project_name:
            raise ValueError("project_name is required for Claude Code ingest")
        return await self.ingest_project(project_name, limit=limit, min_size_kb=min_size_kb)

    async def distill_session(
        self,
        session_id: str,
        project_name: str,
        category: str | None = None,
        *,
        session_project_name: str | None = None,
    ) -> list[MemoryEntry]:
        """Run heuristic pattern matching (not AI extraction) over a session.

        Scans session transcript for reusable project knowledge using
        heuristic regex patterns (see :data:`parser.HEURISTIC_PATTERNS`):

        - technical decisions ("we decided to use X")
        - conventions ("I always use X", "the standard is Y")
        - bug workarounds ("the fix was X", "workaround: Y")
        - architecture notes ("I organized X into Y")

        .. note::

           This is **heuristic-based**, not AI-powered.  For higher-quality
           extraction with dedup, clustering, and cross-session synthesis,
           use the ``session-distill`` skill instead.

        If *category* is specified, only entries matching that category are
        returned/saved.  Returns all newly saved entries for this session.
        """
        project_dir = self.sessions_dir / (session_project_name or project_name)
        if not project_dir.exists():
            return []

        # Find the session file
        session_file = None
        for sf in project_dir.glob("*.jsonl"):
            if session_id in sf.name:
                session_file = sf
                break

        if not session_file:
            return []

        turns = self.parse_jsonl_session(session_file)
        entries = self._extract_entries(turns, project_name, session_id)

        # Filter by category if specified
        if category:
            entries = [e for e in entries if e.category == category]

        if not entries:
            return []

        if self.backend is None:
            raise RuntimeError("ClaudeCodeAdapter.distill_session requires an initialized backend")

        existing_entries = await self.backend.structured_store.list_memory_entries(
            project_name,
            limit=10000,
        )
        existing_keys = {
            self._entry_key(entry.category, entry.content, entry.source)
            for entry in existing_entries
        }

        saved_entries: list[MemoryEntry] = []
        for entry in entries:
            entry_key = self._entry_key(entry.category, entry.content, entry.source)
            if entry_key in existing_keys:
                continue
            await self.backend.structured_store.save_memory_entry(entry)
            existing_keys.add(entry_key)
            saved_entries.append(entry)

        return saved_entries

    async def distill_relation_facts(
        self,
        session_id: str,
        project_name: str,
        *,
        session_project_name: str | None = None,
    ) -> list[RelationFact]:
        """Extract and save explicit RelationFact records from a session."""
        project_dir = self.sessions_dir / (session_project_name or project_name)
        if not project_dir.exists():
            return []

        session_file = None
        for sf in project_dir.glob("*.jsonl"):
            if session_id in sf.name:
                session_file = sf
                break

        if not session_file:
            return []

        turns = self.parse_jsonl_session(session_file)
        facts = extract_relation_facts(turns, project_name, session_id)
        if not facts:
            return []

        if self.backend is None:
            raise RuntimeError("ClaudeCodeAdapter.distill_relation_facts requires an initialized backend")

        existing_facts = await self.backend.structured_store.list_relation_facts(
            project_name,
            limit=10000,
        )
        existing_keys = {
            self._relation_fact_key(fact.source_entity, fact.relation_type, fact.target_entity, fact.source)
            for fact in existing_facts
        }

        saved_facts: list[RelationFact] = []
        for fact in facts:
            fact_key = self._relation_fact_key(
                fact.source_entity,
                fact.relation_type,
                fact.target_entity,
                fact.source,
            )
            if fact_key in existing_keys:
                continue
            await self.backend.structured_store.save_relation_fact(fact)
            existing_keys.add(fact_key)
            saved_facts.append(fact)

        return saved_facts

    def _extract_entries(
        self,
        turns: list[dict[str, Any]],
        project_name: str,
        session_id: str,
    ) -> list[MemoryEntry]:
        """Run heuristic extraction over parsed turns.

        Delegates to :func:`harness_mem.adapters.parser.extract_heuristic_entries`.
        This is a heuristic (regex) extraction, **not** AI-powered distillation.
        For higher-quality extraction, use the ``session-distill`` skill.
        """
        return extract_heuristic_entries(turns, project_name, session_id)

    @staticmethod
    def _select_observation_turns(
        turns: list[dict[str, Any]],
        *,
        max_turns: int,
    ) -> list[tuple[int, dict[str, Any]]]:
        if len(turns) <= max_turns:
            return list(enumerate(turns, 1))

        head_count = max_turns // 2
        tail_count = max_turns - head_count
        head = list(enumerate(turns[:head_count], 1))
        tail_start = len(turns) - tail_count + 1
        tail = list(enumerate(turns[-tail_count:], tail_start))
        return head + tail

    @staticmethod
    def _entry_key(category: str, content: str, source: str) -> tuple[str, str, str]:
        normalized = " ".join(content.lower().split())
        return (category, normalized, source)

    @staticmethod
    def _relation_fact_key(
        source_entity: str,
        relation_type: str,
        target_entity: str,
        source: str,
    ) -> tuple[str, str, str, str]:
        return (
            source_entity.strip().lower(),
            relation_type.strip().lower(),
            target_entity.strip().lower(),
            source,
        )

    @staticmethod
    def _session_sort_key(session: SessionRecord) -> datetime:
        """Sort key for session dicts. Delegates to :func:`parser.session_sort_key`."""
        return session_sort_key(session)
