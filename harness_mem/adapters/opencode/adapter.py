"""Read OpenCode's SQLite session store without modifying it.

OpenCode stores sessions in a SQLite database under its XDG data directory.
The adapter intentionally uses the public table shape from OpenCode's source
(``session``, ``message`` and ``part``) and treats missing/older schemas as an
unavailable source rather than guessing from configuration files.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

DEFAULT_DATABASE_NAMES = (
    "opencode.db",
    "opencode-prod.db",
    "opencode-beta.db",
    "opencode-latest.db",
)


class OpenCodeAdapter:
    """Adapter for OpenCode's local SQLite transcript database."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        database_path: Path | None = None,
        *,
        home_dir: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        self.home_dir = Path.home() if home_dir is None else home_dir
        self.project_root = (
            normalize_project_root(project_root.expanduser())
            if project_root is not None
            else None
        )
        self.database_path = database_path or self._find_database()

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name, min_size_kb
        if self.database_path is None:
            return []
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT id, directory, title, time_created, time_updated "
                    "FROM session ORDER BY time_updated DESC, id DESC"
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            self._issue(issues, "opencode_database_unreadable", str(exc), self.database_path)
            return []

        sessions: list[SessionRecord] = []
        for session_id, directory, title, created, updated in rows:
            if not self._directory_matches(directory):
                continue
            mtime = _epoch_millis(updated or created) or datetime.fromtimestamp(
                self.database_path.stat().st_mtime,
                tz=timezone.utc,
            )
            sessions.append(
                {
                    "path": self.database_path,
                    "name": str(title or session_id),
                    "session_id": str(session_id),
                    "size_kb": self.database_path.stat().st_size / 1024,
                    "size_bytes": self.database_path.stat().st_size,
                    "size": f"{self.database_path.stat().st_size / 1024:.1f}KB",
                    "mtime": mtime,
                    "mtime_ns": self.database_path.stat().st_mtime_ns,
                    "cwd": str(directory or ""),
                }
            )
        return sessions if limit is None else sessions[:limit]

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        del issues
        with _connect_readonly(session_path) as db:
            session = db.execute(
                "SELECT directory, title, time_updated FROM session WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError(f"OpenCode session not found: {session_id}")
            messages = db.execute(
                "SELECT id, data, time_created FROM message "
                "WHERE session_id = ? ORDER BY time_created, id",
                (session_id,),
            ).fetchall()
            parts = db.execute(
                "SELECT message_id, data FROM part WHERE session_id = ? ORDER BY message_id, id",
                (session_id,),
            ).fetchall()

        parts_by_message: dict[str, list[dict[str, Any]]] = {}
        for message_id, data in parts:
            parsed = _decode_json(data)
            if isinstance(parsed, dict):
                parts_by_message.setdefault(str(message_id), []).append(parsed)

        lines = [f"# OpenCode Session: {session_id}"]
        if session[0]:
            lines.append(f"\nWorkspace: {session[0]}")
        if session[1]:
            lines.append(f"\nTitle: {session[1]}")
        for message_id, data, _created in messages:
            message = _decode_json(data)
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").lower()
            label = "User" if role == "user" else "Assistant" if role == "assistant" else role.title()
            text = _message_text(message, parts_by_message.get(str(message_id), []))
            if text:
                lines.append(f"\n{label}: {text[:4000]}")
            tools = _message_tools(parts_by_message.get(str(message_id), []))
            if tools:
                lines.append(f"\nTools: {', '.join(tools[:10])}")

        raw_content = "\n".join(lines)
        timestamp = _epoch_millis(session[2]) or datetime.fromtimestamp(
            session_path.stat().st_mtime,
            tz=timezone.utc,
        )
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="opencode",
            raw_content=raw_content[:50000],
            content_type="transcript",
            timestamp=timestamp,
            metadata={
                "project_name": project_name,
                "project_root": str(self.project_root) if self.project_root else None,
                "opencode_database": str(session_path),
                "opencode_session_id": session_id,
            },
            tags=["session", "opencode"],
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("OpenCodeAdapter.ingest requires an initialized backend")
        sessions = self.list_sessions(project_name, min_size_kb=min_size_kb, limit=limit)
        existing = {
            item.session_id
            for item in await self.backend.verbatim_store.list(limit=100000)
            if item.client == "opencode"
            and (project_name is None or item.metadata.get("project_name") == project_name)
        }
        ingested = 0
        skipped = 0
        errors: list[Issue] = []
        for session in sessions:
            session_id = str(session["session_id"])
            if session_id in existing:
                skipped += 1
                continue
            try:
                await self.backend.verbatim_store.save(
                    self.session_to_observation(session["path"], session_id, project_name)
                )
                existing.add(session_id)
                ingested += 1
            except Exception as exc:  # noqa: BLE001 - report one bad session and continue
                errors.append({
                    "level": "error",
                    "code": "session_ingest_failed",
                    "message": f"Failed to ingest OpenCode session {session_id}: {exc}",
                    "path": str(session["path"]),
                    "session_id": session_id,
                })
        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "sessions_found": len(sessions),
            "candidate_sessions": len(sessions),
            "ingested": ingested,
            "skipped_existing": skipped,
            "errors": len(errors),
            "error_details": errors,
        }

    def _find_database(self) -> Path | None:
        roots = (
            self.home_dir / ".local" / "share" / "opencode",
            self.home_dir / "AppData" / "Local" / "opencode",
            self.home_dir / "AppData" / "Roaming" / "opencode",
            self.home_dir / ".config" / "opencode",
            self.home_dir / ".opencode",
        )
        candidates = [root / name for root in roots for name in DEFAULT_DATABASE_NAMES]
        existing = [path for path in candidates if path.is_file()]
        return max(existing, key=lambda path: path.stat().st_mtime) if existing else None

    def _connect(self) -> sqlite3.Connection:
        if self.database_path is None:
            raise FileNotFoundError("No OpenCode database found")
        return _connect_readonly(self.database_path)

    def _directory_matches(self, directory: object) -> bool:
        if self.project_root is None:
            return True
        if not isinstance(directory, str) or not directory.strip():
            return False
        return _same_or_child_path(Path(directory), self.project_root)

    @staticmethod
    def _issue(issues: list[Issue] | None, code: str, message: str, path: Path) -> None:
        if issues is not None:
            issues.append({"level": "warning", "code": code, "message": message, "path": str(path)})


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def _decode_json(value: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _message_text(message: dict[str, Any], parts: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for key in ("content", "text"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    for part in parts:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            values.append(part["text"].strip())
        if part.get("type") == "reasoning" and isinstance(part.get("text"), str):
            values.append(part["text"].strip())
    return "\n".join(value for value in values if value)


def _message_tools(parts: list[dict[str, Any]]) -> list[str]:
    return [str(part.get("tool")) for part in parts if part.get("type") == "tool" and part.get("tool")]


def _epoch_millis(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _same_or_child_path(value: Path, root: Path) -> bool:
    value_text = str(value).replace("/", "\\").rstrip("\\").lower()
    root_text = str(root).replace("/", "\\").rstrip("\\").lower()
    return value_text == root_text or value_text.startswith(root_text + "\\")


__all__ = ["DEFAULT_DATABASE_NAMES", "OpenCodeAdapter"]
