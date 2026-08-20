"""Codex Archive adapter — ingest legacy Codex rollout sessions into harness-mem."""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import (
    parse_codex_archive_jsonl_session,
    render_codex_conversation,
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import normalize_source_root, sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.transcript_chunking import source_uri_from_path

# Default Codex archived sessions directory
DEFAULT_ARCHIVE_DIR = Path.home() / ".codex" / "archived_sessions"
ArchiveCursor = dict[str, Any]


def _is_path_within(child: Path, parent: Path) -> bool:
    try:
        child_text = os.path.normcase(str(child.expanduser().resolve()))
        parent_text = os.path.normcase(str(parent.expanduser().resolve()))
    except OSError:
        child_text = os.path.normcase(str(child.expanduser()))
        parent_text = os.path.normcase(str(parent.expanduser()))
    return child_text == parent_text or child_text.startswith(parent_text.rstrip("\\/") + os.sep)


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
        cursor: ArchiveCursor | None = None,
        project_root: Path | None = None,
        scope: str = "project",
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
        if not self.archive_dir.is_dir():
            self._append_issue(
                issues,
                level="warning",
                code="archive_dir_invalid",
                message=f"Codex archive path is not a directory: {self.archive_dir}",
                path=self.archive_dir,
            )
            return []

        sessions: list[SessionRecord] = []
        for session_file in self.archive_dir.glob("rollout-*.jsonl"):
            try:
                stat_result = session_file.stat()
                size_kb = stat_result.st_size / 1024
                # For large archives, we don't count lines eagerly to save time
                if cursor is not None and not self._is_newer_than_cursor(session_file, stat_result, cursor):
                    continue
                header = self._read_session_header(session_file, issues=issues)
                cwd = str(header.get("cwd") or "")
                if scope == "project" and project_root is not None:
                    if not cwd or not _is_path_within(Path(cwd), project_root):
                        continue
                sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": header.get("id") or session_file.stem.removeprefix("rollout-"),
                    "size_kb": size_kb,
                    "size_bytes": stat_result.st_size,
                    "size": f"{size_kb:.1f}KB",
                    "lines": 0,
                    "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
                    "mtime_ns": stat_result.st_mtime_ns,
                    "cwd": cwd,
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

    def parse_jsonl_session(
        self,
        session_path: Path,
        issues: list[Issue] | None = None,
        *,
        content: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Parse an archived Codex rollout into metadata plus normalized turns."""
        return parse_codex_archive_jsonl_session(
            session_path,
            issues=issues,
            content=content,
        )

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        """Convert an archived rollout session to a normalized observation."""
        meta, turns = self.parse_jsonl_session(session_path, issues=issues)
        return self._observation_from_turns(
            session_path,
            session_id,
            project_name,
            meta=meta,
            turns=turns,
        )

    def _observation_from_turns(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None,
        *,
        meta: dict[str, Any],
        turns: list[dict[str, Any]],
    ) -> Observation:
        if not turns:
            raise ValueError(f"Codex archive session {session_id} contained no transcript turns")
        raw_content = render_codex_conversation(turns)
        if not raw_content:
            raise ValueError(
                f"Codex archive session {session_id} contained no user or assistant messages"
            )

        metadata = {
            "source_archive": str(self.archive_dir),
            "original_id": meta.get("session_id"),
        }
        if project_name:
            metadata["project_name"] = project_name
        if meta.get("cwd"):
            metadata["cwd"] = meta["cwd"]

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="codex-archive",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc),
            metadata=metadata,
            tags=["session", "codex", "archive"],
        )

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
        *,
        project_root: Path | None = None,
        issues: list[Issue] | None = None,
    ) -> TranscriptSyncResult:
        """Capture one exact archived Codex source revision."""

        if self.backend is None:
            raise RuntimeError(
                "CodexArchiveAdapter.sync_session requires an initialized backend"
            )
        native_bytes = session_path.read_bytes()
        native_text = native_bytes.decode("utf-8", errors="replace")
        meta, turns = self.parse_jsonl_session(
            session_path,
            issues=issues,
            content=native_text,
        )
        observation = self._observation_from_turns(
            session_path,
            session_id,
            project_name,
            meta=meta,
            turns=turns,
        )
        source_text = render_codex_conversation(turns)
        if not source_text:
            raise ValueError(
                f"Codex archive session {session_id} contained no user or assistant messages"
            )
        persisted_bytes = source_text.encode("utf-8")
        root = project_root or Path(
            str(observation.metadata.get("cwd") or Path.cwd())
        )
        stat_result = session_path.stat()
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(root),
            client="codex-archive",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=source_uri_from_path(session_path),
            source_text=source_text,
            raw_bytes=persisted_bytes,
            native_input_bytes=native_bytes,
            mtime_ns=stat_result.st_mtime_ns,
            sequence_count=len(turns),
            parser_version="codex-archive-conversation-v2",
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
        *,
        full_rescan: bool = False,
        cursor_path: Path | None = None,
        project_root: Path | None = None,
        scope: str = "project",
    ) -> dict:
        """Ingest legacy Codex rollout sessions."""
        warnings: list[Issue] = []
        error_details: list[Issue] = []
        all_sessions = self.list_sessions(min_size_kb=min_size_kb, issues=warnings, scope="all")
        if scope == "all" or not all_sessions:
            scoped_sessions = all_sessions
        else:
            scoped_sessions = self.list_sessions(
                min_size_kb=min_size_kb,
                issues=warnings,
                project_root=project_root,
                scope=scope,
            )
        if self.backend is None:
            raise RuntimeError("CodexArchiveAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Codex archive ingest")

        source_root = normalize_source_root(self.archive_dir)
        if full_rescan:
            self.backend.transcript_store.reset_scan_frontier(
                project_name=project_name,
                client="codex-archive",
                source_root=source_root,
            )

        async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
            return await self.sync_session(
                session["path"],
                session["session_id"],
                project_name,
                project_root=project_root,
                issues=warnings,
            )

        scan = await sync_sessions_fairly(
            self.backend.transcript_store,
            project_name=project_name,
            client="codex-archive",
            source_root=source_root,
            sessions=scoped_sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            error_details.append({
                    "level": "error",
                    "code": "archive_ingest_failed",
                    "message": f"Failed to ingest archive {session_id}: {failure.error}",
                    "path": str(failure.session["path"]),
                    "session_id": session_id,
                })

        return {
            "sessions_found": len(all_sessions),
            "scoped_sessions": len(scoped_sessions),
            "candidate_sessions": scan.sessions_scanned,
            "sessions_scanned": scan.sessions_scanned,
            "ingested": scan.ingested,
            "updated": scan.updated,
            "unchanged": scan.unchanged,
            "skipped_existing": scan.unchanged,
            "errors": len(scan.failures),
            "warnings": warnings,
            "error_details": error_details,
            "scan_mode": "full_rescan" if full_rescan else "frontier",
            "scan_frontier": scan.frontier.to_dict(),
            "scope": scope,
            "project_root": str(project_root) if project_root else None,
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

    def _read_session_header(self, session_path: Path, *, issues: list[Issue] | None = None) -> dict[str, Any]:
        try:
            with session_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                for _ in range(12):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        record = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if record.get("type") != "session_meta":
                        continue
                    payload = record.get("payload")
                    if isinstance(payload, dict):
                        return payload
        except OSError as exc:
            self._append_issue(
                issues,
                level="warning",
                code="session_header_read_failed",
                message=f"Failed to read archive header {session_path}: {exc}",
                path=session_path,
            )
        return {}

    async def _existing_session_ids(self, project_name: str | None) -> set[str]:
        if self.backend is None:
            return set()
        observations = await self.backend.verbatim_store.list(limit=100000)
        return {
            observation.session_id
            for observation in observations
            if observation.client == "codex-archive"
            and (project_name is None or observation.metadata.get("project_name") == project_name)
        }

    @staticmethod
    def _session_cursor_key(session: SessionRecord) -> tuple[int, int, str]:
        return (
            int(session.get("mtime_ns", 0)),
            int(session.get("size_bytes", 0)),
            str(session.get("path", "")),
        )

    @classmethod
    def _cursor_from_session(cls, session: SessionRecord) -> ArchiveCursor:
        return {
            "mtime_ns": int(session.get("mtime_ns", 0)),
            "size_bytes": int(session.get("size_bytes", 0)),
            "path": str(session.get("path", "")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _is_newer_than_cursor(
        session_path: Path,
        stat_result: Any,
        cursor: ArchiveCursor,
    ) -> bool:
        current = (
            int(getattr(stat_result, "st_mtime_ns", 0)),
            int(getattr(stat_result, "st_size", 0)),
            str(session_path),
        )
        saved = (
            int(cursor.get("mtime_ns", 0)),
            int(cursor.get("size_bytes", 0)),
            str(cursor.get("path", "")),
        )
        # Use path only as a stable tiebreaker when mtime+size collide.
        return current > saved

    def _load_cursor(
        self,
        cursor_path: Path | None,
        *,
        issues: list[Issue] | None = None,
    ) -> ArchiveCursor | None:
        if cursor_path is None or not cursor_path.exists():
            return None
        try:
            data = json.loads(cursor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._append_issue(
                issues,
                level="warning",
                code="archive_cursor_invalid",
                message=f"Failed to read archive ingest cursor {cursor_path}: {exc}",
                path=cursor_path,
            )
            return None
        if not isinstance(data, dict):
            return None
        return data

    @staticmethod
    def _write_cursor(cursor_path: Path, cursor: ArchiveCursor) -> None:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        cursor_path.write_text(json.dumps(cursor, indent=2), encoding="utf-8")
