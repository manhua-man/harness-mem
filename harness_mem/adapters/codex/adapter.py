"""Codex adapter — ingest Codex CLI sessions into harness-mem."""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import parse_codex_jsonl_session, session_sort_key
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.interfaces.memory_backend import MemoryBackend

# Default Codex session directory
DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
Issue = dict[str, str]


class CodexAdapter:
    """Adapter for ingesting Codex CLI sessions.

    Reads session data from ~/.codex/sessions/ and converts them
    to Observations for search-only (V1) use. Distillation/correction
    flows go through the Claude Code adapter.
    """

    def __init__(self, backend: MemoryBackend, sessions_dir: Path | None = None):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR

    def list_sessions(
        self,
        min_size_kb: int = 1,
        issues: list[Issue] | None = None,
    ) -> list[dict[str, Any]]:
        """List session files from the sessions directory."""
        if not self.sessions_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_missing",
                message=f"Codex sessions directory does not exist: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []
        if not self.sessions_dir.is_dir():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_invalid",
                message=f"Codex sessions path is not a directory: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []

        sessions: list[dict[str, Any]] = []
        for session_file in self.sessions_dir.glob("**/*.jsonl"):
            try:
                stat_result = session_file.stat()
                size_kb = stat_result.st_size / 1024
                line_count = len(
                    session_file.read_text(
                        encoding="utf-8-sig",
                        errors="replace",
                    ).splitlines()
                )
            except OSError as exc:
                self._append_issue(
                    issues,
                    level="warning",
                    code="session_scan_failed",
                    message=f"Failed to inspect Codex session file {session_file}: {exc}",
                    path=session_file,
                )
                continue
            if size_kb >= min_size_kb:
                sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": session_file.stem,
                    "size_kb": size_kb,
                    "size": f"{size_kb:.1f}KB",
                    "lines": line_count,
                    "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
                })
        return sorted(sessions, key=self._session_sort_key, reverse=True)

    def parse_jsonl_session(
        self,
        session_path: Path,
        issues: list[Issue] | None = None,
    ) -> list[dict[str, Any]]:
        """Parse a Codex .jsonl session file into turns.

        Delegates to :func:`harness_mem.adapters.parser.parse_codex_jsonl_session`.
        """
        return parse_codex_jsonl_session(session_path, issues=issues)

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        issues: list[Issue] | None = None,
    ) -> Observation:
        """Convert a parsed session to a single Observation."""
        turns = self.parse_jsonl_session(session_path, issues=issues)

        lines = [f"# Codex Session: {session_id}"]
        for i, turn in enumerate(turns[:20], 1):
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for resp in turn["assistant"][:3]:
                    lines.append(f"\nAssistant: {resp[:500]}")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        metadata = {"sessions_dir": str(self.sessions_dir)}
        if project_name:
            metadata["project_name"] = project_name

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="codex",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata=metadata,
            tags=["session", "codex"],
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 1,
    ) -> dict:
        """Ingest recent Codex sessions.

        Returns dict with counts of ingested observations.
        """
        warnings: list[Issue] = []
        error_details: list[Issue] = []
        all_sessions = self.list_sessions(0, issues=warnings)
        sessions = [
            session for session in all_sessions
            if session.get("size_kb", 0) >= min_size_kb
        ][:limit]

        ingested = 0
        errors = 0

        for session in sessions:
            session_id = session["name"].replace(".jsonl", "")
            try:
                obs = self.session_to_observation(
                    session["path"],
                    session_id,
                    project_name,
                    issues=warnings,
                )
            except Exception as exc:
                errors += 1
                error_details.append(self._build_issue(
                    level="error",
                    code="session_parse_failed",
                    message=(
                        f"Failed to parse Codex session {session_id} "
                        f"({session['path']}): {exc}"
                    ),
                    path=session["path"],
                    session_id=session_id,
                ))
                continue
            try:
                await self.backend.verbatim_store.save(obs)
                ingested += 1
            except Exception as exc:
                errors += 1
                error_details.append(self._build_issue(
                    level="error",
                    code="session_save_failed",
                    message=f"Failed to save Codex session {session_id} ({exc})",
                    path=session["path"],
                    session_id=session_id,
                ))

        return {
            "sessions_found": len(all_sessions),
            "ingested": ingested,
            "errors": errors,
            "warnings": warnings,
            "error_details": error_details,
        }

    @staticmethod
    def _session_sort_key(session: dict[str, Any]) -> datetime:
        """Sort key for session dicts. Delegates to :func:`parser.session_sort_key`."""
        return session_sort_key(session)

    @staticmethod
    def _build_issue(
        level: str,
        code: str,
        message: str,
        path: Path | None = None,
        session_id: str | None = None,
    ) -> Issue:
        issue: Issue = {
            "level": level,
            "code": code,
            "message": message,
        }
        if path is not None:
            issue["path"] = str(path)
        if session_id is not None:
            issue["session_id"] = session_id
        return issue

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
        issues.append(self._build_issue(level, code, message, path, session_id))
