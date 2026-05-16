"""Codex Archive adapter — ingest legacy Codex rollout sessions into harness-mem."""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, session_sort_key
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.interfaces.memory_backend import MemoryBackend

# Default Codex archived sessions directory
DEFAULT_ARCHIVE_DIR = Path.home() / ".codex" / "archived_sessions"


class CodexArchiveAdapter:
    """Adapter for ingesting legacy Codex rollout sessions.

    Reads rollout-*.jsonl files from archived_sessions directory and
    converts them to high-fidelity Observations.
    """

    def __init__(self, backend: MemoryBackend | None, archive_dir: Path | None = None):
        self.backend = backend
        self.archive_dir = archive_dir or DEFAULT_ARCHIVE_DIR

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """List rollout session files from the archive directory."""
        del project_name
        if not self.archive_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="archive_dir_missing",
                message=f"Codex archive directory does not exist: {self.archive_dir}",
                path=self.archive_dir,
            )
            return []

        sessions: list[SessionRecord] = []
        for session_file in self.archive_dir.glob("rollout-*.jsonl"):
            try:
                stat_result = session_file.stat()
                size_kb = stat_result.st_size / 1024
                # For large archives, we don't count lines eagerly to save time
                sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": session_file.stem,
                    "size_kb": size_kb,
                    "size": f"{size_kb:.1f}KB",
                    "lines": 0,
                    "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
                })
            except OSError as exc:
                self._append_issue(
                    issues,
                    level="warning",
                    code="session_scan_failed",
                    message=f"Failed to inspect archive file {session_file}: {exc}",
                    path=session_file,
                )
                continue
        
        ordered = sorted(sessions, key=self._session_sort_key, reverse=True)
        if limit is not None:
            return ordered[:limit]
        return ordered

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict:
        """Ingest legacy Codex rollout sessions."""
        warnings: list[Issue] = []
        error_details: list[Issue] = []
        all_sessions = self.list_sessions(min_size_kb=min_size_kb, issues=warnings)
        sessions = all_sessions[:limit]

        ingested = 0
        errors = 0
        if self.backend is None:
            raise RuntimeError("CodexArchiveAdapter.ingest requires an initialized backend")

        for session in sessions:
            session_id = session["session_id"]
            try:
                meta, turns = parse_codex_archive_jsonl_session(
                    session["path"],
                    issues=warnings,
                )
                if not turns:
                    continue

                # Build rich observation content
                lines = [f"# Codex Archived Session: {session_id}"]
                if meta.get("cwd"):
                    lines.append(f"CWD: {meta['cwd']}")
                if meta.get("start_timestamp"):
                    lines.append(f"Started: {meta['start_timestamp']}")
                
                for i, turn in enumerate(turns, 1):
                    lines.append(f"\n## Turn {i} ({turn.get('turn_id', 'unknown')})")
                    if turn.get("user"):
                        lines.append(f"\nUser: {turn['user']}")
                    for assistant_msg in turn.get("assistant", []):
                        lines.append(f"\nAssistant: {assistant_msg}")
                    for tool in turn.get("tools", []):
                        lines.append(f"\nTool: {tool.get('name')} -> {tool.get('input')}")

                raw_content = "\n".join(lines)
                
                metadata = {
                    "source_archive": str(self.archive_dir),
                    "original_id": meta.get("session_id"),
                }
                if project_name:
                    metadata["project_name"] = project_name
                if meta.get("cwd"):
                    metadata["cwd"] = meta["cwd"]

                obs = Observation(
                    id=str(uuid4()),
                    session_id=session_id,
                    client="codex-archive",
                    raw_content=raw_content,
                    content_type="transcript",
                    timestamp=session["mtime"], # Fallback to file mtime
                    metadata=metadata,
                    tags=["session", "codex", "archive"],
                )
                
                await self.backend.verbatim_store.save(obs)
                ingested += 1

            except Exception as exc:
                errors += 1
                error_details.append({
                    "level": "error",
                    "code": "archive_ingest_failed",
                    "message": f"Failed to ingest archive {session_id}: {exc}",
                    "path": str(session["path"]),
                    "session_id": session_id,
                })

        return {
            "sessions_found": len(all_sessions),
            "ingested": ingested,
            "errors": errors,
            "warnings": warnings,
            "error_details": error_details,
        }

    @staticmethod
    def _session_sort_key(session: SessionRecord) -> datetime:
        return session_sort_key(session)

    def _append_issue(
        self,
        issues: list[Issue] | None,
        *,
        level: str,
        code: str,
        message: str,
        path: Path | None = None,
        session_id: str | None = None,
    ) -> None:
        if issues is None:
            return
        issue: Issue = {"level": level, "code": code, "message": message}
        if path:
            issue["path"] = str(path)
        if session_id:
            issue["session_id"] = session_id
        issues.append(issue)
