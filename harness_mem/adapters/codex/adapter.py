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
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


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

    Current Codex stores native sessions as ``rollout-*.jsonl`` under
    ``~/.codex/sessions/YYYY/MM/DD``.  The older ``codex-archive`` adapter
    remains separate for explicit archive imports.
    """

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        project_root: Path | str | None = None,
        scope: str = "project",
    ):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
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

        sessions: list[SessionRecord] = []
        for session_file in self.sessions_dir.glob("**/rollout-*.jsonl"):
            try:
                stat_result = session_file.stat()
                size_kb = stat_result.st_size / 1024
                if size_kb < min_size_kb:
                    continue
                header = self._read_session_header(session_file, issues=issues)
                cwd = str(header.get("cwd") or "")
                if effective_scope == "project" and effective_project_root is not None:
                    if not cwd or not _is_path_within(Path(cwd), effective_project_root):
                        continue
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
                })
            except OSError as exc:
                self._append_issue(
                    issues,
                    level="warning",
                    code="session_scan_failed",
                    message=f"Failed to inspect Codex session file {session_file}: {exc}",
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
        """Parse a native Codex rollout into metadata plus normalized turns."""
        return parse_codex_archive_jsonl_session(session_path, issues=issues)

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
        if not turns:
            raise ValueError(f"Codex session {session_id} contained no transcript turns")

        lines = [f"# Codex Session: {session_id}"]
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
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        metadata = {
            "sessions_dir": str(self.sessions_dir),
            "original_id": meta.get("session_id"),
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
        sessions = scoped_sessions[:limit]

        ingested = 0
        errors = 0
        skipped_existing = 0
        if self.backend is None:
            raise RuntimeError("CodexAdapter.ingest requires an initialized backend")

        existing_session_ids = await self._existing_session_ids(project_name)
        for session in sessions:
            session_id = session["session_id"]
            if session_id in existing_session_ids:
                skipped_existing += 1
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
            except Exception as exc:
                errors += 1
                error_details.append(self._build_issue(
                    level="error",
                    code="session_ingest_failed",
                    message=f"Failed to ingest Codex session {session_id} ({exc})",
                    path=session["path"],
                    session_id=session_id,
                ))

        return {
            "sessions_found": len(all_sessions),
            "scoped_sessions": len(scoped_sessions),
            "candidate_sessions": len(sessions),
            "ingested": ingested,
            "skipped_existing": skipped_existing,
            "errors": errors,
            "warnings": warnings,
            "error_details": error_details,
            "scope": self.scope,
            "project_root": str(self.project_root) if self.project_root else None,
        }

    @staticmethod
    def _session_sort_key(session: SessionRecord) -> datetime:
        return session_sort_key(session)

    def _read_session_header(self, session_path: Path, *, issues: list[Issue] | None = None) -> dict[str, Any]:
        fallback: dict[str, Any] = {}
        try:
            with session_path.open("r", encoding="utf-8", errors="replace") as handle:
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
