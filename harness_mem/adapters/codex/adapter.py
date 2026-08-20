"""Codex adapter - ingest current Codex rollout sessions into harness-mem."""

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
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
DEFAULT_ARCHIVE_DIR = Path.home() / ".codex" / "archived_sessions"


def _is_path_within(child: Path, parent: Path) -> bool:
    try:
        child_text = os.path.normcase(str(child.expanduser().resolve()))
        parent_text = os.path.normcase(str(parent.expanduser().resolve()))
    except OSError:
        child_text = os.path.normcase(str(child.expanduser()))
        parent_text = os.path.normcase(str(parent.expanduser()))
    return child_text == parent_text or child_text.startswith(parent_text.rstrip("\\/") + os.sep)


class CodexAdapter:
    """Adapter for ingesting current Codex CLI/Desktop rollout sessions.

    Current Codex stores native sessions under ``~/.codex/sessions`` and moves
    older rollouts into ``~/.codex/archived_sessions``. Both roots form one
    logical Codex source family.
    """

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        archive_dir: Path | None = None,
        project_root: Path | str | None = None,
        scope: str = "project",
    ):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self.archive_dir = archive_dir or (
            DEFAULT_ARCHIVE_DIR
            if sessions_dir is None
            else self.sessions_dir.parent / "archived_sessions"
        )
        try:
            self.source_root = Path(
                os.path.commonpath((self.sessions_dir, self.archive_dir))
            )
        except ValueError:
            self.source_root = self.sessions_dir.parent
        self.project_root = Path(project_root).expanduser() if project_root is not None else None
        self.scope = scope

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
        project_root: Path | str | None = None,
        scope: str | None = None,
    ) -> list[SessionRecord]:
        """List native Codex rollout session files."""
        del project_name
        effective_scope = scope or self.scope
        effective_project_root = (
            Path(project_root).expanduser()
            if project_root is not None
            else self.project_root
        )

        sessions: list[SessionRecord] = []
        roots = (
            ("codex-current", self.sessions_dir),
            ("codex-archive", self.archive_dir),
        )
        for source_kind, root in roots:
            if not root.exists():
                continue
            if not root.is_dir():
                self._append_issue(
                    issues,
                    level="warning",
                    code="sessions_dir_invalid",
                    message=f"Codex transcript path is not a directory: {root}",
                    path=root,
                )
                continue
            for session_file in root.glob("**/rollout-*.jsonl"):
                self._append_session_record(
                    sessions,
                    session_file,
                    source_kind=source_kind,
                    min_size_kb=min_size_kb,
                    effective_scope=effective_scope,
                    effective_project_root=effective_project_root,
                    issues=issues,
                )

        deduped: dict[str, SessionRecord] = {}
        for session in sessions:
            session_id = session["session_id"]
            previous = deduped.get(session_id)
            if previous is None or (
                previous.get("source_kind") == "codex-archive"
                and session.get("source_kind") == "codex-current"
            ):
                deduped[session_id] = session

        ordered = sorted(deduped.values(), key=self._session_sort_key, reverse=True)
        if limit is not None:
            return ordered[:limit]
        return ordered

    def _append_session_record(
        self,
        sessions: list[SessionRecord],
        session_file: Path,
        *,
        source_kind: str,
        min_size_kb: int,
        effective_scope: str,
        effective_project_root: Path | None,
        issues: list[Issue] | None,
    ) -> None:
        try:
            stat_result = session_file.stat()
            size_kb = stat_result.st_size / 1024
            if size_kb < min_size_kb:
                return
            header = self._read_session_header(session_file, issues=issues)
            cwd = str(header.get("cwd") or "")
            if effective_scope == "project" and effective_project_root is not None:
                if not cwd or not _is_path_within(Path(cwd), effective_project_root):
                    return
            sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": str(header.get("id") or session_file.stem.removeprefix("rollout-")),
                    "size_kb": size_kb,
                    "size_bytes": stat_result.st_size,
                    "size": f"{size_kb:.1f}KB",
                    "lines": 0,
                    "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
                    "mtime_ns": stat_result.st_mtime_ns,
                    "cwd": cwd,
                    "source_kind": source_kind,
                })
        except OSError as exc:
            self._append_issue(
                issues,
                level="warning",
                code="session_scan_failed",
                message=f"Failed to inspect Codex session file {session_file}: {exc}",
                path=session_file,
            )

    def parse_jsonl_session(
        self,
        session_path: Path,
        issues: list[Issue] | None = None,
        *,
        content: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Parse a native Codex rollout into metadata plus normalized turns."""
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
        """Convert a native Codex rollout session to a normalized observation."""
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
            raise ValueError(f"Codex session {session_id} contained no transcript turns")
        raw_content = render_codex_conversation(turns)
        if not raw_content:
            raise ValueError(f"Codex session {session_id} contained no user or assistant messages")

        metadata = {
            "sessions_dir": str(self.sessions_dir),
            "archive_dir": str(self.archive_dir),
            "original_id": meta.get("session_id"),
            "source_kind": (
                "codex-archive"
                if _is_path_within(session_path, self.archive_dir)
                else "codex-current"
            ),
        }
        if project_name:
            metadata["project_name"] = project_name
        if meta.get("cwd"):
            metadata["cwd"] = meta["cwd"]
        if self.project_root is not None:
            metadata["project_root"] = str(self.project_root)

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="codex",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc),
            metadata=metadata,
            tags=["session", "codex"],
        )

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
        *,
        issues: list[Issue] | None = None,
    ) -> TranscriptSyncResult:
        """Capture one exact Codex source revision and its search rendering."""

        if self.backend is None:
            raise RuntimeError("CodexAdapter.sync_session requires an initialized backend")
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
            raise ValueError(f"Codex session {session_id} contained no user or assistant messages")
        persisted_bytes = source_text.encode("utf-8")
        project_root = self.project_root or Path(
            str(observation.metadata.get("cwd") or Path.cwd())
        )
        stat_result = session_path.stat()
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(project_root),
            client="codex",
            session_id=session_id,
            source_kind=str(observation.metadata["source_kind"]),
            source_uri=source_uri_from_path(session_path),
            source_text=source_text,
            raw_bytes=persisted_bytes,
            native_input_bytes=native_bytes,
            mtime_ns=stat_result.st_mtime_ns,
            sequence_count=len(turns),
            parser_version="codex-conversation-v2",
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        """Ingest recent native Codex sessions."""
        warnings: list[Issue] = []
        error_details: list[Issue] = []
        all_sessions = self.list_sessions(min_size_kb=min_size_kb, issues=warnings, scope="all")
        if self.scope == "all" or not all_sessions:
            scoped_sessions = all_sessions
        else:
            scoped_sessions = self.list_sessions(
                min_size_kb=min_size_kb,
                issues=warnings,
                project_root=self.project_root,
                scope=self.scope,
            )
        if self.backend is None:
            raise RuntimeError("CodexAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Codex ingest")

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
            client="codex",
            source_root=self.source_root,
            sessions=scoped_sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            error_details.append(self._build_issue(
                    level="error",
                    code="session_ingest_failed",
                    message=f"Failed to ingest Codex session {session_id} ({failure.error})",
                    path=failure.session["path"],
                    session_id=session_id,
                ))

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
            "scan_frontier": scan.frontier.to_dict(),
            "scope": self.scope,
            "project_root": str(self.project_root) if self.project_root else None,
        }

    @staticmethod
    def _session_sort_key(session: SessionRecord) -> datetime:
        return session_sort_key(session)

    def _read_session_header(self, session_path: Path, *, issues: list[Issue] | None = None) -> dict[str, Any]:
        fallback: dict[str, Any] = {}
        try:
            with session_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                for _ in range(50):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        record = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    if record.get("type") == "session_meta":
                        return payload
                    if not fallback and isinstance(payload.get("cwd"), str):
                        fallback = {
                            "cwd": payload.get("cwd"),
                            "id": payload.get("id"),
                            "timestamp": payload.get("timestamp"),
                        }
        except OSError as exc:
            self._append_issue(
                issues,
                level="warning",
                code="session_header_read_failed",
                message=f"Failed to read Codex session header {session_path}: {exc}",
                path=session_path,
            )
        return fallback

    async def _existing_session_ids(self, project_name: str | None) -> set[str]:
        if self.backend is None:
            return set()
        observations = await self.backend.verbatim_store.list(limit=100000)
        return {
            observation.session_id
            for observation in observations
            if observation.client == "codex"
            and (project_name is None or observation.metadata.get("project_name") == project_name)
        }

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
