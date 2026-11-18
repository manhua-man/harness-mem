"""Read the current SQLite store and the earlier OpenCode JSON session tree."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import (
    normalize_project_root,
)
from harness_mem.adapters.opencode.legacy import (
    OpenCodeSourceError,
    legacy_dependencies,
    legacy_session_info,
    legacy_session_paths,
    read_legacy_rows,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.adapters.source_metadata import metadata_record
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_DATABASE_NAMES = (
    "opencode.db",
    "opencode-prod.db",
    "opencode-beta.db",
    "opencode-latest.db",
)
_SQLITE_KIND = "sqlite-session-export"
_LEGACY_KIND = "opencode-legacy-json"


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
    """Adapter for read-only OpenCode session sources."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        database_path: Path | None = None,
        *,
        home_dir: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        self.home_dir = (Path.home() if home_dir is None else home_dir).absolute()
        self.project_root = _normalize_workspace_path(project_root)
        self._auto_database = database_path is None
        self._profiles: tuple[Path, ...]
        self._database_candidates: tuple[Path, ...]
        if database_path is not None:
            database_path = database_path.absolute()
            self._profiles = (database_path.parent,)
            self._database_candidates = (database_path,)
        else:
            self._profiles = self._profile_roots(use_environment=home_dir is None)
            self._database_candidates = tuple(
                root / name for root in self._profiles for name in DEFAULT_DATABASE_NAMES
            )
        self.database_path = database_path or self._find_database()

    def list_session_metadata(
        self, *, min_size_kb: int = 0, limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """Read session headers; verify duplicate-format bodies on selection."""
        sqlite_sessions = self._list_sqlite_metadata(issues)
        records: dict[str, SessionRecord] = {row["session_id"]: row for row in sqlite_sessions}
        legacy: dict[str, list[Path]] = {}
        for profile in self._profiles:
            for path in legacy_session_paths(profile / "storage"):
                legacy.setdefault(path.stem, []).append(path)
        for session_id, paths in legacy.items():
            if len(paths) > 1:
                self._issue(issues, "opencode_duplicate_legacy_session", session_id, paths[0])
                continue
            path = paths[0]
            if session_id in records:
                continue  # The selected SQLite read must corroborate this copy.
            try:
                info, _ = legacy_session_info(path, session_id)
                record = metadata_record(
                    path, session_id, project_roots=[info["directory"]], source_kind=_LEGACY_KIND,
                    metadata_paths=[path, path.parent, path.parent.parent],
                )
                record["name"] = str(info.get("title") or session_id)
                stamp = info.get("time")
                if isinstance(stamp, dict):
                    record["mtime"] = _epoch_millis(stamp.get("updated") or stamp.get("created")) or record["mtime"]
                records[session_id] = record
            except (OSError, OpenCodeSourceError) as exc:
                self._issue(issues, getattr(exc, "reason_code", "opencode_legacy_unreadable"), str(exc), path)
        sessions = sorted(
            (row for row in records.values()
             if row["size_kb"] >= min_size_kb and self._directory_matches(row.get("cwd"))),
            key=lambda row: (row["mtime"], row["session_id"]), reverse=True,
        )
        return sessions if limit is None else sessions[:limit]

    def _list_sqlite_metadata(self, issues: list[Issue] | None) -> list[SessionRecord]:
        path = self.database_path
        if path is None:
            return []
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT id, directory, title, time_created, time_updated "
                    "FROM session ORDER BY time_updated DESC, id DESC"
                ).fetchall()
            sessions: list[SessionRecord] = []
            for session_id, directory, title, created, updated in rows:
                if not session_id:
                    continue
                roots = [directory] if isinstance(directory, str) and directory.strip() else []
                record = metadata_record(
                    path, str(session_id), project_roots=roots, source_kind=_SQLITE_KIND,
                    # WAL commits can change session rows without touching the DB.
                    metadata_paths=[path, path.with_name(path.name + "-wal")],
                )
                record["name"] = str(title or session_id)
                record["mtime"] = _epoch_millis(updated or created) or record["mtime"]
                if not roots or not Path(roots[0]).is_absolute():
                    record["metadata_status"] = "unknown"
                    record.pop("cwd", None)
                sessions.append(record)
        except (OSError, sqlite3.Error) as exc:
            self._issue(issues, "opencode_database_unreadable", str(exc), path)
            return []
        return sessions

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name
        return self.list_session_metadata(min_size_kb=min_size_kb, limit=limit, issues=issues)

    def _legacy_matches(self, session_id: str) -> list[Path]:
        return [
            path for profile in self._profiles
            for path in legacy_session_paths(profile / "storage", session_id)
        ]

    def session_dependency_paths(self, record: SessionRecord) -> list[Path]:
        """Selected-source dependencies include each record and its membership."""
        return self._source_dependencies(record["path"], self._legacy_matches(record["session_id"]), record["session_id"])

    def _source_dependencies(self, path: Path, legacy: list[Path], session_id: str) -> list[Path]:
        dependencies = [path]
        for database in self._database_candidates:
            dependencies.extend((database, database.with_name(database.name + "-wal")))
        for profile in self._profiles:
            session_root = profile / "storage" / "session"
            dependencies.append(session_root)
            if session_root.is_dir():
                # An existing bucket can gain another copy of this session.
                dependencies.extend(bucket for bucket in sorted(session_root.iterdir()) if bucket.is_dir())
        for legacy_path in legacy:
            dependencies.extend(legacy_dependencies(legacy_path, session_id))
        return list(dict.fromkeys(dependencies))

    def _read_source_export(self, path: Path, session_id: str) -> tuple[_SessionExport, str]:
        path = path.absolute()
        if self._auto_database and self._find_database() != self.database_path:
            raise OpenCodeSourceError("opencode_source_dependencies_changed", session_id)
        legacy = self._legacy_matches(session_id)
        if len(legacy) > 1:
            raise OpenCodeSourceError("opencode_duplicate_legacy_session", session_id)
        if path == self.database_path:
            kind = _SQLITE_KIND
        elif path in legacy:
            kind = _LEGACY_KIND
        else:
            raise OpenCodeSourceError("opencode_source_not_discovered", session_id)
        dependencies = self._source_dependencies(path, legacy, session_id)
        before = _dependency_state(dependencies)
        sqlite_export = None
        if self.database_path is not None and self.database_path.is_file():
            try:
                with closing(self._connect()) as db:
                    sqlite_export = _export_session(db, session_id)
            except OpenCodeSourceError as exc:
                if kind == _SQLITE_KIND or exc.reason_code != "opencode_session_not_found":
                    raise
            except (OSError, sqlite3.Error) as exc:
                raise OpenCodeSourceError("opencode_database_unreadable", session_id) from exc
        legacy_export = None
        if legacy:
            source = read_legacy_rows(legacy[0], session_id)
            legacy_export = _encode_export(
                source.session, source.messages, source.parts, session_id, native_files=source.files,
            )
            if sqlite_export is not None and not _equivalent_exports(sqlite_export, legacy_export):
                raise OpenCodeSourceError("opencode_dual_format_conflict", session_id)
        if (self._legacy_matches(session_id) != legacy
                or (self._auto_database and self._find_database() != self.database_path)
                or self._source_dependencies(path, legacy, session_id) != dependencies
                or _dependency_state(dependencies) != before):
            raise OpenCodeSourceError("opencode_source_dependencies_changed", session_id)
        exported = sqlite_export if kind == _SQLITE_KIND else legacy_export
        if exported is None or not self._directory_matches(exported.session.get("directory")):
            raise OpenCodeSourceError("opencode_session_not_found", session_id)
        return exported, kind

    def read_session_source(self, session_path: Path, session_id: str) -> dict[str, Any]:
        exported, kind = self._read_source_export(session_path, session_id)
        return {
            "raw_bytes": exported.raw_bytes,
            "source_text": exported.source_text,
            "source_uri": _source_uri(session_path, session_id, kind),
            "project_roots": [str(exported.session.get("directory") or "")],
        }

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        del issues
        exported, kind = self._read_source_export(session_path, session_id)

        return self._export_to_observation(
            exported,
            session_path,
            session_id,
            project_name,
            kind,
        )

    def _export_to_observation(
        self,
        exported: _SessionExport,
        session_path: Path,
        session_id: str,
        project_name: str | None,
        source_kind: str,
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
                **({"opencode_database": str(session_path)} if source_kind == _SQLITE_KIND else {}),
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
        """Persist one deterministic, complete per-session export."""

        if self.backend is None:
            raise RuntimeError(
                "OpenCodeAdapter.sync_session requires an initialized backend"
            )
        exported, kind = self._read_source_export(session_path, session_id)

        observation = self._export_to_observation(
            exported,
            session_path,
            session_id,
            project_name,
            kind,
        )
        project_root = str(self.project_root or exported.session.get("directory") or "")
        effective_project_name = project_name or _project_name_from_root(project_root)
        updated = exported.session.get("time_updated")
        mtime_ns = (
            int(updated * 1_000_000) if isinstance(updated, (int, float)) else None
        )
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=effective_project_name,
            project_root=project_root,
            client="opencode",
            session_id=session_id,
            source_kind=kind,
            source_uri=_source_uri(session_path, session_id, kind),
            source_text=exported.source_text,
            raw_bytes=exported.raw_bytes,
            mtime_ns=mtime_ns,
            sequence_count=exported.sequence_count,
            parser_version="opencode-sqlite-v1" if kind == _SQLITE_KIND else "opencode-legacy-json-v1",
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int | None = None,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("OpenCodeAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for OpenCode ingest")
        errors: list[Issue] = []
        sessions = self.list_sessions(project_name, min_size_kb=min_size_kb, issues=errors)

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
                    "code": getattr(failure.error, "reason_code", "session_ingest_failed"),
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

    def _profile_roots(self, *, use_environment: bool) -> tuple[Path, ...]:
        if use_environment:
            native_home = os.environ.get("OPENCODE_HOME")
            if native_home and (native_profile := Path(native_home).expanduser()).is_absolute():
                return (native_profile,)
        roots = (
            self.home_dir / ".local" / "share" / "opencode",
            self.home_dir / "AppData" / "Local" / "opencode",
            self.home_dir / "AppData" / "Roaming" / "opencode",
            self.home_dir / ".config" / "opencode",
            self.home_dir / ".opencode",
        )
        xdg = os.environ.get("XDG_DATA_HOME") if use_environment else None
        if xdg and (xdg_path := Path(xdg).expanduser()).is_absolute():
            return tuple(dict.fromkeys((xdg_path / "opencode", *roots)))
        return roots

    def _find_database(self) -> Path | None:
        existing = [path for path in self._database_candidates if path.is_file()]
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
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _export_session(db: sqlite3.Connection, session_id: str) -> _SessionExport:
    db.execute("BEGIN")
    session_row = db.execute(
        "SELECT * FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        raise OpenCodeSourceError("opencode_session_not_found", session_id)
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
    return _encode_export(session, messages, parts, session_id)


def _encode_export(
    session: dict[str, Any], messages: list[dict[str, Any]], parts: list[dict[str, Any]],
    session_id: str, *, native_files: dict[str, str] | None = None,
) -> _SessionExport:
    records = [
        {"format": "harness-mem-opencode-session-v1", "session_id": session_id,
         **({"native_files": native_files} if native_files is not None else {})},
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


def _source_uri(path: Path, session_id: str, kind: str) -> str:
    uri = source_uri_from_path(path)
    return f"{uri}#session={quote(session_id, safe='')}" if kind == _SQLITE_KIND else uri


def _dependency_state(paths: list[Path]) -> list[tuple[int, int, int] | None]:
    state: list[tuple[int, int, int] | None] = []
    for path in paths:
        try:
            stamp = path.stat()
        except FileNotFoundError:
            state.append(None)
        else:
            state.append((stamp.st_mtime_ns, stamp.st_size, stamp.st_ino))
    return state


def _equivalent_exports(sqlite_export: _SessionExport, legacy_export: _SessionExport) -> bool:
    """The native migration copies the complete message and part JSON data."""
    database, legacy = sqlite_export.session, legacy_export.session
    database_dir, legacy_dir = database.get("directory"), legacy.get("directory")
    if (not isinstance(database_dir, str) or not isinstance(legacy_dir, str)
            or not Path(database_dir).is_absolute() or not Path(legacy_dir).is_absolute()
            or os.path.normcase(str(Path(database_dir).resolve())) != os.path.normcase(str(Path(legacy_dir).resolve()))):
        return False
    for key, native_key in (("project_id", "projectID"), ("parent_id", "parentID"), ("title", "title")):
        if key in database and native_key in legacy and database[key] != legacy[native_key]:
            return False
    for sql_rows, json_rows in ((sqlite_export.messages, legacy_export.messages), (sqlite_export.parts, legacy_export.parts)):
        if len(sql_rows) != len(json_rows):
            return False
        for sql_row, json_row in zip(sql_rows, json_rows):
            if any(sql_row.get(key) != json_row.get(key) for key in ("id", "session_id", "message_id")):
                return False
            decoded = _decode_json(sql_row.get("data"))
            if not isinstance(decoded, dict) or json.dumps(decoded, sort_keys=True) != json.dumps(json_row["data"], sort_keys=True):
                return False
    return True


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
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _normalize_workspace_path(path: Path | None) -> str | None:
    if path is None:
        return None
    raw = str(path.expanduser())
    if re.match(r"^[A-Za-z]:[\\/]", raw) and not Path(raw).is_absolute():
        return raw
    return str(normalize_project_root(Path(raw)))


def _same_or_child_path(value: Path, root: str) -> bool:
    normalized_value = _normalize_workspace_path(value)
    if normalized_value is None:
        return False
    value_text = normalized_value.replace("/", "\\").rstrip("\\").lower()
    root_text = str(root).replace("/", "\\").rstrip("\\").lower()
    return value_text == root_text or value_text.startswith(root_text + "\\")


def _project_name_from_root(project_root: str) -> str:
    stripped = project_root.replace("\\", "/").rstrip("/")
    return stripped.rsplit("/", 1)[-1] if stripped else "default"


__all__ = ["DEFAULT_DATABASE_NAMES", "OpenCodeAdapter"]
