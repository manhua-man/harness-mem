"""Ingest Hermes JSON sessions and SQLite ``state.db`` transcripts."""

from __future__ import annotations

import base64
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import (
    normalize_project_root,
)
from harness_mem.adapters.parser import (
    parse_hermes_json_session,
    read_hermes_session_id,
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_SESSIONS_DIR = Path.home() / ".hermes" / "sessions"


class HermesAdapter:
    """Adapter for Hermes ``session_*.json`` and ``sessions/messages`` SQLite."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        *,
        state_db: Path | None = None,
        home_dir: Path | None = None,
        project_root: Path | None = None,
        scope: str = "project",
    ) -> None:
        self.backend = backend
        self.home_dir = Path.home() if home_dir is None else home_dir
        self.sessions_dir = sessions_dir or (
            DEFAULT_SESSIONS_DIR
            if home_dir is None
            else self.home_dir / ".hermes" / "sessions"
        )
        self.state_db = (
            state_db
            if state_db is not None
            else _find_state_db(self.home_dir)
            if sessions_dir is None
            else None
        )
        self.scope = scope
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
        if not self.sessions_dir.exists() and self.state_db is None:
            self._append_issue(
                issues,
                level="warning",
                code="hermes_sources_missing",
                message="Hermes JSON sessions and state.db were not found",
                path=self.sessions_dir.parent,
            )
            return []

        all_sessions = self._all_session_records(
            min_size_kb=min_size_kb,
            issues=issues,
        )

        scoped_sessions = [session for session in all_sessions if self._record_matches_scope(session)]
        ordered = sorted(scoped_sessions, key=session_sort_key, reverse=True)
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
        if self._is_state_db(session_path):
            exported = _export_state_db_session(session_path, session_id)
            return self._state_export_to_observation(
                exported,
                session_path,
                session_id,
                project_name,
            )
        turns = parse_hermes_json_session(
            session_path,
            issues=issues,
        )

        lines = [f"# Hermes Session: {session_id}"]
        for i, turn in enumerate(turns, 1):
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user']}")
            if turn.get("assistant"):
                for response in turn["assistant"]:
                    lines.append(f"\nAssistant: {response}")
            if turn.get("tools"):
                tool_names = [tool["name"] for tool in turn["tools"]]
                lines.append(f"\nTools: {', '.join(tool_names)}")

        raw_content = "\n".join(lines)

        metadata: dict[str, Any] = {
            "project_name": project_name,
            "hermes_sessions_dir": str(self.sessions_dir),
            "scope": self.scope,
        }
        if self.project_root is not None:
            metadata["project_root"] = str(self.project_root)

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="hermes",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata=metadata,
            tags=["session", "hermes"],
        )

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
        *,
        issues: list[Issue] | None = None,
    ) -> TranscriptSyncResult:
        """Capture exact source bytes and upsert the derived observation."""

        if self.backend is None:
            raise RuntimeError(
                "HermesAdapter.sync_session requires an initialized backend"
            )
        if self._is_state_db(session_path):
            exported = _export_state_db_session(session_path, session_id)
            native_bytes = exported["raw_bytes"]
            source_text = exported["source_text"]
            observation = self._state_export_to_observation(
                exported,
                session_path,
                session_id,
                project_name,
            )
            source_kind = "sqlite-session-export"
            source_uri = (
                f"{source_uri_from_path(session_path)}#session={quote(session_id, safe='')}"
            )
            ended_at = exported["session"].get("ended_at") or exported["session"].get(
                "started_at"
            )
            mtime_ns = int(float(ended_at) * 1_000_000_000) if ended_at else None
            sequence_count = 1 + len(exported["messages"])
            parser_version = "hermes-state-db-v1"
        else:
            native_bytes = session_path.read_bytes()
            source_text = native_bytes.decode("utf-8-sig", errors="replace")
            observation = self.session_to_observation(
                session_path,
                session_id,
                project_name,
                issues=issues,
            )
            source_kind = "json"
            source_uri = source_uri_from_path(session_path)
            mtime_ns = session_path.stat().st_mtime_ns
            sequence_count = len(source_text.splitlines())
            parser_version = "hermes-json-v1"
        project_root = self.project_root or Path.cwd()
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(project_root),
            client="hermes",
            session_id=session_id,
            source_kind=source_kind,
            source_uri=source_uri,
            source_text=source_text,
            raw_bytes=native_bytes,
            mtime_ns=mtime_ns,
            sequence_count=sequence_count,
            parser_version=parser_version,
            reuse_logical_session=True,
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 1,
    ) -> dict[str, Any]:
        warnings: list[Issue] = []
        all_sessions = self._all_session_records(
            min_size_kb=min_size_kb,
            issues=warnings,
        )
        scoped_sessions = [session for session in all_sessions if self._record_matches_scope(session)]
        scoped_sessions = sorted(scoped_sessions, key=session_sort_key, reverse=True)

        error_details: list[Issue] = []
        if self.backend is None:
            raise RuntimeError("HermesAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Hermes ingest")

        async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
            return await self.sync_session(
                session["path"],
                session["session_id"],
                project_name,
                issues=warnings,
            )

        scan = await sync_sessions_fairly(
            self.backend.transcript_store,
            project_name=project_name,
            client="hermes",
            source_root=self._source_root(),
            sessions=scoped_sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            issue: Issue = {
                "level": "error",
                "code": "session_ingest_failed",
                "message": f"Failed to ingest Hermes session {session_id}: {failure.error}",
                "path": str(failure.session["path"]),
                "session_id": session_id,
            }
            error_details.append(issue)
            warnings.append(issue)

        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "scope": self.scope,
            "sessions_found": len(all_sessions),
            "scoped_sessions": len(scoped_sessions),
            "candidate_sessions": scan.sessions_scanned,
            "sessions_scanned": scan.sessions_scanned,
            "ingested": scan.ingested,
            "updated": scan.updated,
            "unchanged": scan.unchanged,
            "errors": len(scan.failures),
            "error_details": error_details,
            "scan_frontier": scan.frontier.to_dict(),
            "warnings": warnings,
        }

    def _all_session_records(
        self,
        *,
        min_size_kb: int,
        issues: list[Issue] | None,
    ) -> list[SessionRecord]:
        records_by_id: dict[str, SessionRecord] = {}
        if self.sessions_dir.exists():
            for session_file in self.sessions_dir.glob("session_*.json"):
                if not session_file.is_file():
                    continue
                size_kb = session_file.stat().st_size / 1024
                if size_kb < min_size_kb:
                    continue
                session_id = read_hermes_session_id(session_file)
                if not session_id:
                    self._append_issue(
                        issues,
                        level="warning",
                        code="invalid_hermes_session",
                        message=f"Hermes session is missing a usable session_id: {session_file}",
                        path=session_file,
                    )
                    continue
                records_by_id[session_id] = {
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": session_id,
                    "size_kb": size_kb,
                    "size_bytes": session_file.stat().st_size,
                    "size": f"{size_kb:.1f}KB",
                    "lines": len(
                        session_file.read_text(
                            encoding="utf-8-sig",
                            errors="replace",
                        ).splitlines()
                    ),
                    "mtime": datetime.fromtimestamp(
                        session_file.stat().st_mtime,
                        tz=timezone.utc,
                    ),
                    "source_kind": "json",
                }
        if self.state_db is not None:
            for record in _state_db_session_records(self.state_db, issues=issues):
                # The authoritative SQLite row wins over an exported JSON copy
                # carrying the same Hermes session id.
                records_by_id[record["session_id"]] = record
        return list(records_by_id.values())

    def _record_matches_scope(self, session: SessionRecord) -> bool:
        if self.scope == "all" or self.project_root is None:
            return True
        if session.get("source_kind") == "sqlite-session-export":
            cwd = session.get("cwd")
            return bool(cwd and _same_or_child_path(Path(cwd), self.project_root))
        return self._session_matches_scope(Path(session["path"]))

    def _is_state_db(self, path: Path) -> bool:
        return bool(
            self.state_db is not None
            and path.resolve(strict=False) == self.state_db.resolve(strict=False)
        )

    def _source_root(self) -> Path:
        if self.state_db is not None:
            return self.state_db.parent
        return self.sessions_dir

    def _state_export_to_observation(
        self,
        exported: dict[str, Any],
        session_path: Path,
        session_id: str,
        project_name: str | None,
    ) -> Observation:
        session = exported["session"]
        lines = [f"# Hermes Session: {session_id}"]
        if session.get("title"):
            lines.append(f"\nTitle: {session['title']}")
        workspace = session.get("git_repo_root") or session.get("cwd")
        if workspace:
            lines.append(f"\nWorkspace: {workspace}")
        for message in exported["messages"]:
            role = str(message.get("role") or "").strip().lower()
            content = str(message.get("content") or "")
            tool_name = str(message.get("tool_name") or "")
            if role == "tool" and tool_name:
                lines.append(f"\nTool: {tool_name} {content}")
            elif content:
                label = "User" if role == "user" else "Assistant" if role == "assistant" else role.title()
                lines.append(f"\n{label}: {content}")
        timestamp = _epoch_seconds(
            session.get("ended_at") or session.get("started_at")
        ) or datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc)
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="hermes",
            raw_content="\n".join(lines),
            content_type="transcript",
            timestamp=timestamp,
            metadata={
                "project_name": project_name,
                "project_root": str(self.project_root or workspace or ""),
                "hermes_state_db": str(session_path),
                "scope": self.scope,
            },
            tags=["session", "hermes", "sqlite"],
        )

    def _session_matches_scope(self, session_path: Path) -> bool:
        if self.scope == "all" or self.project_root is None:
            return True
        variants = _project_root_variants(self.project_root)
        try:
            text = session_path.read_text(
                encoding="utf-8-sig", errors="replace"
            ).lower()
        except OSError:
            return False
        return any(variant in text for variant in variants)

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


def _project_root_variants(project_root: Path) -> set[str]:
    text = str(project_root)
    slash = text.replace("\\", "/")
    backslash = text.replace("/", "\\")
    doubled_backslash = backslash.replace("\\", "\\\\")
    return {
        variant.lower()
        for variant in (text, slash, backslash, doubled_backslash)
        if variant
    }


def _find_state_db(home_dir: Path) -> Path | None:
    override = os.environ.get("HERMES_STATE_DB")
    hermes_home = os.environ.get("HERMES_HOME")
    candidates = [
        *( [Path(override).expanduser()] if override else [] ),
        *( [Path(hermes_home).expanduser() / "state.db"] if hermes_home else [] ),
        home_dir / "AppData" / "Local" / "hermes" / "state.db",
        home_dir / ".hermes" / "state.db",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _state_db_session_records(
    path: Path,
    *,
    issues: list[Issue] | None,
) -> list[SessionRecord]:
    try:
        with closing(_connect_readonly(path)) as db:
            rows = db.execute(
                "SELECT * FROM sessions WHERE COALESCE(archived, 0) = 0 "
                "ORDER BY started_at DESC, id DESC"
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        if issues is not None:
            issues.append(
                {
                    "level": "warning",
                    "code": "hermes_state_db_unreadable",
                    "message": str(exc),
                    "path": str(path),
                }
            )
        return []
    size_bytes = path.stat().st_size
    records: list[SessionRecord] = []
    for row in rows:
        data = dict(row)
        session_id = str(data.get("id") or "")
        if not session_id:
            continue
        ended_at = data.get("ended_at") or data.get("started_at")
        records.append(
            {
                "path": path,
                "name": str(data.get("title") or session_id),
                "session_id": session_id,
                "size_kb": size_bytes / 1024,
                "size_bytes": size_bytes,
                "size": f"{size_bytes / 1024:.1f}KB",
                "lines": int(data.get("message_count") or 0),
                "mtime": _epoch_seconds(ended_at)
                or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                "mtime_ns": int(float(ended_at) * 1_000_000_000)
                if ended_at
                else path.stat().st_mtime_ns,
                "cwd": str(data.get("git_repo_root") or data.get("cwd") or ""),
                "source_kind": "sqlite-session-export",
            }
        )
    return records


def _export_state_db_session(path: Path, session_id: str) -> dict[str, Any]:
    with closing(_connect_readonly(path)) as db:
        db.execute("BEGIN")
        session_row = db.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise ValueError(f"Hermes session not found: {session_id}")
        message_rows = db.execute(
            "SELECT * FROM messages WHERE session_id = ? "
            "AND COALESCE(active, 1) = 1 ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    session = dict(session_row)
    messages = [dict(row) for row in message_rows]
    records = [
        {"format": "harness-mem-hermes-state-db-v1", "session_id": session_id},
        {"row": _encode_sqlite_row(session), "table": "sessions"},
        *(
            {"row": _encode_sqlite_row(message), "table": "messages"}
            for message in messages
        ),
    ]
    source_text = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in records
    )
    return {
        "session": session,
        "messages": messages,
        "source_text": source_text,
        "raw_bytes": source_text.encode("ascii"),
    }


def _encode_sqlite_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _encode_sqlite_value(value) for key, value in row.items()}


def _encode_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$sqlite_blob_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"$sqlite_float": repr(value)}
    return value


def _epoch_seconds(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _same_or_child_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.expanduser().resolve(strict=False).relative_to(
            root.expanduser().resolve(strict=False)
        )
        return True
    except ValueError:
        return False


__all__ = ["DEFAULT_SESSIONS_DIR", "HermesAdapter"]
