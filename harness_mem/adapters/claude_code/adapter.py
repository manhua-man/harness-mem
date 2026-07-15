"""Claude Code adapter — ingest Claude Code sessions into harness-mem."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import (
    list_session_files,
    parse_claude_jsonl_session,
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.schemas import Observation
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.transcript_chunking import source_uri_from_path


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
        for i, turn in enumerate(turns, 1):
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user']}")
            if turn.get("assistant"):
                for resp in turn["assistant"]:
                    lines.append(f"\nAssistant: {resp}")
            if turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"]]
                lines.append(f"\nTools: {', '.join(tool_names)}")

        raw_content = "\n".join(lines)

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

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
        *,
        project_root: Path | None = None,
    ) -> TranscriptSyncResult:
        """Capture exact source bytes and upsert the derived Observation."""

        if self.backend is None:
            raise RuntimeError("ClaudeCodeAdapter.sync_session requires an initialized backend")
        native_bytes = session_path.read_bytes()
        source_text = native_bytes.decode("utf-8-sig", errors="replace")
        observation = self.turns_to_observation(session_path, session_id, project_name)
        root = project_root or Path.cwd()
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(root),
            client="claude-code",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=source_uri_from_path(session_path),
            source_text=source_text,
            raw_bytes=native_bytes,
            mtime_ns=session_path.stat().st_mtime_ns,
            sequence_count=source_text.count("\n") + int(bool(source_text)),
            parser_version="claude-code-jsonl-v1",
        )

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

        if self.backend is None:
            raise RuntimeError("ClaudeCodeAdapter.ingest requires an initialized backend")

        async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
            return await self.sync_session(
                session["path"],
                session["session_id"],
                project_name,
            )

        source_root = sessions[0]["path"].parent if sessions else self.sessions_dir / project_name
        scan = await sync_sessions_fairly(
            self.backend.transcript_store,
            project_name=project_name,
            client="claude-code",
            source_root=source_root,
            sessions=sessions,
            change_limit=limit,
            sync_session=sync_one,
        )

        return {
            "project_name": project_name,
            "sessions_found": len(self.list_project_sessions(project_name, 0)),
            "sessions_scanned": scan.sessions_scanned,
            "ingested": scan.ingested,
            "updated": scan.updated,
            "unchanged": scan.unchanged,
            "errors": len(scan.failures),
            "error_details": [
                {
                    "session_id": failure.session["session_id"],
                    "path": str(failure.session["path"]),
                    "message": str(failure.error),
                }
                for failure in scan.failures
            ],
            "scan_frontier": scan.frontier.to_dict(),
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
    def _session_sort_key(session: SessionRecord) -> datetime:
        """Sort key for session dicts. Delegates to :func:`parser.session_sort_key`."""
        return session_sort_key(session)
