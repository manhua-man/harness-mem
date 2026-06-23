"""Codex Archive adapter — ingest legacy Codex rollout sessions into harness-mem."""

from __future__ import annotations
import json
import os
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
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Parse an archived Codex rollout into metadata plus normalized turns."""
        return parse_codex_archive_jsonl_session(session_path, issues=issues)

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
        if not turns:
            raise ValueError(f"Codex archive session {session_id} contained no transcript turns")

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
        cursor = None if full_rescan else self._load_cursor(cursor_path, issues=warnings)
        candidate_sessions = scoped_sessions
        if cursor is not None and scoped_sessions:
            candidate_sessions = self.list_sessions(
                min_size_kb=min_size_kb,
                issues=warnings,
                cursor=cursor,
                project_root=project_root,
                scope=scope,
            )
        sessions = candidate_sessions[:limit]

        ingested = 0
        errors = 0
        skipped_existing = 0
        if self.backend is None:
            raise RuntimeError("CodexArchiveAdapter.ingest requires an initialized backend")

        existing_session_ids = await self._existing_session_ids(project_name)
        committed_sessions: list[SessionRecord] = []
        for session in sessions:
            session_id = session["session_id"]
            if session_id in existing_session_ids:
                skipped_existing += 1
                committed_sessions.append(session)
                continue
            try:
                obs = self.session_to_observation(
                    session["path"],
                    session_id,
                    project_name,
                    issues=warnings,
                )
                await self.backend.verbatim_store.save(obs)
                ingested += 1
                existing_session_ids.add(session_id)
                committed_sessions.append(session)

            except Exception as exc:
                errors += 1
                error_details.append({
                    "level": "error",
                    "code": "archive_ingest_failed",
                    "message": f"Failed to ingest archive {session_id}: {exc}",
                    "path": str(session["path"]),
                    "session_id": session_id,
                })

        if cursor_path is not None and committed_sessions:
            self._write_cursor(
                cursor_path,
                self._cursor_from_session(max(committed_sessions, key=self._session_cursor_key)),
            )

        return {
            "sessions_found": len(all_sessions),
            "scoped_sessions": len(scoped_sessions),
            "candidate_sessions": len(candidate_sessions),
            "ingested": ingested,
            "skipped_existing": skipped_existing,
            "errors": errors,
            "warnings": warnings,
            "error_details": error_details,
            "scan_mode": "full_rescan" if full_rescan else "incremental",
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
            with session_path.open("r", encoding="utf-8", errors="replace") as handle:
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
