"""Grok adapter — ingest Grok CLI chat history into harness-mem."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.parser import parse_grok_jsonl_session, session_sort_key
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

DEFAULT_SESSIONS_DIR = Path.home() / ".grok" / "sessions"


class GrokAdapter:
    """Adapter for ingesting Grok ``chat_history.jsonl`` transcripts."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        *,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self.project_root = (
            normalize_project_root(project_root.expanduser())
            if project_root is not None
            else None
        )

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 1,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name
        if not self.sessions_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_missing",
                message=f"Grok sessions directory does not exist: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []

        project_dirs = self._matching_project_dirs(issues=issues)
        sessions: list[SessionRecord] = []
        for project_dir in project_dirs:
            for session_dir in project_dir.iterdir():
                chat_history = session_dir / "chat_history.jsonl"
                if not chat_history.is_file():
                    continue
                size_kb = chat_history.stat().st_size / 1024
                if size_kb < min_size_kb:
                    continue
                sessions.append(
                    {
                        "path": chat_history,
                        "name": chat_history.name,
                        "session_id": session_dir.name,
                        "size_kb": size_kb,
                        "size_bytes": chat_history.stat().st_size,
                        "size": f"{size_kb:.1f}KB",
                        "lines": len(
                            chat_history.read_text(
                                encoding="utf-8-sig",
                                errors="replace",
                            ).splitlines()
                        ),
                        "mtime": datetime.fromtimestamp(
                            chat_history.stat().st_mtime,
                            tz=timezone.utc,
                        ),
                    }
                )

        ordered = sorted(sessions, key=session_sort_key, reverse=True)
        if limit is not None:
            return ordered[:limit]
        return ordered

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        turns = parse_grok_jsonl_session(session_path, issues=issues)

        lines = [f"# Grok Session: {session_id}"]
        display_turns = self._select_observation_turns(turns, max_turns=20)
        for i, turn in display_turns:
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for response in turn["assistant"][:3]:
                    lines.append(f"\nAssistant: {response[:500]}")
            if turn.get("tools"):
                tool_names = [tool["name"] for tool in turn["tools"][:5]]
                lines.append(f"\nTools: {', '.join(tool_names)}")
            if i == 10 and len(turns) > 20:
                omitted = len(turns) - 20
                lines.append(f"\n[... {omitted} middle turns omitted ...]")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        metadata: dict[str, Any] = {
            "project_name": project_name,
            "grok_sessions_dir": str(self.sessions_dir),
        }
        if self.project_root is not None:
            metadata["project_root"] = str(self.project_root)

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="grok",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc),
            metadata=metadata,
            tags=["session", "grok"],
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 1,
    ) -> dict[str, Any]:
        warnings: list[Issue] = []
        sessions = self.list_sessions(
            project_name=project_name,
            min_size_kb=min_size_kb,
            limit=limit,
            issues=warnings,
        )

        ingested = 0
        errors = 0
        skipped_existing = 0
        if self.backend is None:
            raise RuntimeError("GrokAdapter.ingest requires an initialized backend")

        existing_session_ids = await self._existing_session_ids(project_name)
        for session in sessions:
            session_id = session["session_id"]
            if session_id in existing_session_ids:
                skipped_existing += 1
                continue
            try:
                observation = self.session_to_observation(
                    session["path"],
                    session_id,
                    project_name,
                    issues=warnings,
                )
                await self.backend.verbatim_store.save(observation)
                ingested += 1
                existing_session_ids.add(session_id)
            except Exception as exc:
                errors += 1
                self._append_issue(
                    warnings,
                    level="error",
                    code="session_ingest_failed",
                    message=f"Failed to ingest Grok session {session_id}: {exc}",
                    path=session["path"],
                    session_id=session_id,
                )

        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "scope": "project" if self.project_root else "all",
            "sessions_found": len(sessions),
            "scoped_sessions": len(sessions),
            "ingested": ingested,
            "skipped_existing": skipped_existing,
            "errors": errors,
            "warnings": warnings,
        }

    async def _existing_session_ids(self, project_name: str | None) -> set[str]:
        if self.backend is None:
            return set()
        observations = await self.backend.verbatim_store.list(limit=100000)
        return {
            observation.session_id
            for observation in observations
            if observation.client == "grok"
            and (project_name is None or observation.metadata.get("project_name") == project_name)
        }

    def _matching_project_dirs(self, *, issues: list[Issue] | None = None) -> list[Path]:
        if self.project_root is None:
            return [path for path in self.sessions_dir.iterdir() if path.is_dir()]

        project_dir = self.sessions_dir / grok_project_bucket(self.project_root)
        if project_dir.is_dir():
            return [project_dir]

        self._append_issue(
            issues,
            level="warning",
            code="grok_project_not_found",
            message=f"No Grok project directory matched workspace root {self.project_root}",
            path=self.project_root,
        )
        return []

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
    def _append_issue(
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
        issue: Issue = {
            "level": level,
            "code": code,
            "message": message,
        }
        if path is not None:
            issue["path"] = str(path)
        if session_id is not None:
            issue["session_id"] = session_id
        issues.append(issue)


def grok_project_bucket(project_root: Path) -> str:
    """Return Grok's URL-encoded project-root bucket name."""

    return quote(str(project_root), safe="")


__all__ = ["DEFAULT_SESSIONS_DIR", "GrokAdapter", "grok_project_bucket"]
