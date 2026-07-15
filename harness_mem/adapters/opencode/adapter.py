"""Read OpenCode's SQLite session store without modifying it.

OpenCode stores sessions in a SQLite database under its XDG data directory.
The adapter intentionally uses the public table shape from OpenCode's source
(``session``, ``message`` and ``part``) and treats missing/older schemas as an
unavailable source rather than guessing from configuration files.
"""

from __future__ import annotations

import base64
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import (
    normalize_project_root,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_DATABASE_NAMES = (
    "opencode.db",
    "opencode-prod.db",
    "opencode-beta.db",
    "opencode-latest.db",
)


@dataclass(frozen=True)
class _SessionExport:
    session: dict[str, Any]
    messages: list[dict[str, Any]]
    parts: list[dict[str, Any]]
    source_text: str
    raw_bytes: bytes

    @property
    def sequence_count(self) -> int:
        return 1 + len(self.messages) + len(self.parts)


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
        self.project_root = _normalize_workspace_path(project_root)
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
            self._issue(
                issues, "opencode_database_unreadable", str(exc), self.database_path
            )
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
            exported = _export_session(db, session_id)

        return self._export_to_observation(
            exported,
            session_path,
            session_id,
            project_name,
        )

    def _export_to_observation(
        self,
        exported: _SessionExport,
        session_path: Path,
        session_id: str,
        project_name: str | None,
    ) -> Observation:
        session = exported.session

        parts_by_message: dict[str, list[dict[str, Any]]] = {}
        for part in exported.parts:
            parsed = _decode_json(part.get("data"))
            if isinstance(parsed, dict):
                parts_by_message.setdefault(str(part.get("message_id")), []).append(
                    parsed
                )

        lines = [f"# OpenCode Session: {session_id}"]
        if session.get("directory"):
            lines.append(f"\nWorkspace: {session['directory']}")
        if session.get("title"):
            lines.append(f"\nTitle: {session['title']}")
        for message_row in exported.messages:
            message_id = str(message_row.get("id"))
            message = _decode_json(message_row.get("data"))
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").lower()
            label = (
                "User"
                if role == "user"
                else "Assistant"
                if role == "assistant"
                else role.title()
            )
            message_parts = parts_by_message.get(message_id, [])
            text = _message_text(message, message_parts)
            if text:
                lines.append(f"\n{label}: {text}")
            tools = _message_tools(message_parts)
            if tools:
                lines.append(f"\nTools: {', '.join(tools)}")

        raw_content = "\n".join(lines)
        timestamp = _epoch_millis(
            session.get("time_updated")
        ) or datetime.fromtimestamp(
            session_path.stat().st_mtime,
            tz=timezone.utc,
        )
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="opencode",
            raw_content=raw_content,
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

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
    ) -> TranscriptSyncResult:
        """Persist one deterministic, complete SQLite session export."""

        if self.backend is None:
            raise RuntimeError(
                "OpenCodeAdapter.sync_session requires an initialized backend"
            )
        with _connect_readonly(session_path) as db:
            exported = _export_session(db, session_id)

        observation = self._export_to_observation(
            exported,
            session_path,
            session_id,
            project_name,
        )
        project_root = str(self.project_root or exported.session.get("directory") or "")
        effective_project_name = project_name or _project_name_from_root(project_root)
        updated = exported.session.get("time_updated")
        mtime_ns = (
            int(updated * 1_000_000) if isinstance(updated, (int, float)) else None
        )
        source_uri = (
            f"{source_uri_from_path(session_path)}#session={quote(session_id, safe='')}"
        )
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=effective_project_name,
            project_root=project_root,
            client="opencode",
            session_id=session_id,
            source_kind="sqlite-session-export",
            source_uri=source_uri,
            source_text=exported.source_text,
            raw_bytes=exported.raw_bytes,
            mtime_ns=mtime_ns,
            sequence_count=exported.sequence_count,
            parser_version="opencode-sqlite-v1",
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("OpenCodeAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for OpenCode ingest")
        sessions = self.list_sessions(project_name, min_size_kb=min_size_kb)
        errors: list[Issue] = []

        async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
            return await self.sync_session(
                session["path"],
                session["session_id"],
                project_name,
            )

        source_root = self.database_path or self.home_dir
        scan = await sync_sessions_fairly(
            self.backend.transcript_store,
            project_name=project_name,
            client="opencode",
            source_root=source_root,
            sessions=sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            errors.append(
                {
                    "level": "error",
                    "code": "session_ingest_failed",
                    "message": f"Failed to ingest OpenCode session {session_id}: {failure.error}",
                    "path": str(failure.session["path"]),
                    "session_id": session_id,
                }
            )
        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "sessions_found": len(sessions),
            "candidate_sessions": scan.sessions_scanned,
            "sessions_scanned": scan.sessions_scanned,
            "ingested": scan.ingested,
            "updated": scan.updated,
            "unchanged": scan.unchanged,
            "skipped_existing": scan.unchanged,
            "errors": len(errors),
            "error_details": errors,
            "scan_frontier": scan.frontier.to_dict(),
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
        return (
            max(existing, key=lambda path: path.stat().st_mtime) if existing else None
        )

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
            issues.append(
                {
                    "level": "warning",
                    "code": code,
                    "message": message,
                    "path": str(path),
                }
            )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _export_session(db: sqlite3.Connection, session_id: str) -> _SessionExport:
    db.execute("BEGIN")
    session_row = db.execute(
        "SELECT * FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        raise ValueError(f"OpenCode session not found: {session_id}")
    message_rows = db.execute(
        "SELECT * FROM message WHERE session_id = ? ORDER BY time_created, id",
        (session_id,),
    ).fetchall()
    part_rows = db.execute(
        "SELECT * FROM part WHERE session_id = ? ORDER BY message_id, id",
        (session_id,),
    ).fetchall()

    session = dict(session_row)
    messages = [dict(row) for row in message_rows]
    parts = [dict(row) for row in part_rows]
    records = [
        {"format": "harness-mem-opencode-session-v1", "session_id": session_id},
        {"row": _encode_sqlite_row(session), "table": "session"},
        *({"row": _encode_sqlite_row(row), "table": "message"} for row in messages),
        *({"row": _encode_sqlite_row(row), "table": "part"} for row in parts),
    ]
    source_text = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in records
    )
    return _SessionExport(
        session=session,
        messages=messages,
        parts=parts,
        source_text=source_text,
        raw_bytes=source_text.encode("ascii"),
    )


def _encode_sqlite_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _encode_sqlite_value(value) for key, value in row.items()}


def _encode_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$sqlite_blob_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"$sqlite_float": repr(value)}
    return value


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
    return [
        str(part.get("tool"))
        for part in parts
        if part.get("type") == "tool" and part.get("tool")
    ]


def _epoch_millis(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _normalize_workspace_path(path: Path | None) -> str | None:
    if path is None:
        return None
    raw = str(path.expanduser())
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return raw
    return str(normalize_project_root(Path(raw)))


def _same_or_child_path(value: Path, root: str) -> bool:
    value_text = str(value).replace("/", "\\").rstrip("\\").lower()
    root_text = str(root).replace("/", "\\").rstrip("\\").lower()
    return value_text == root_text or value_text.startswith(root_text + "\\")


def _project_name_from_root(project_root: str) -> str:
    stripped = project_root.replace("\\", "/").rstrip("/")
    return stripped.rsplit("/", 1)[-1] if stripped else "default"


__all__ = ["DEFAULT_DATABASE_NAMES", "OpenCodeAdapter"]
