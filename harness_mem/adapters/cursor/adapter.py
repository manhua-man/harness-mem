"""Cursor adapter — ingest Cursor agent transcripts into harness-mem."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.parser import (
    list_session_files,
    parse_cursor_jsonl_session,
    session_sort_key,
)
from harness_mem.adapters.claude_code.project_profile_detector import (
    normalize_project_root,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_PROJECTS_DIR = Path.home() / ".cursor" / "projects"


class CursorAdapter:
    """Adapter for ingesting Cursor JSONL agent transcripts."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        projects_dir: Path | None = None,
        *,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        self.projects_dir = projects_dir or DEFAULT_PROJECTS_DIR
        self.project_root_text = str(project_root) if project_root is not None else None
        self.project_root = (
            _normalize_cursor_project_root(project_root)
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
        if not self.projects_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="projects_dir_missing",
                message=f"Cursor projects directory does not exist: {self.projects_dir}",
                path=self.projects_dir,
            )
            return []

        project_dirs = self._matching_project_dirs(issues=issues)
        sessions: list[SessionRecord] = []
        for project_dir in project_dirs:
            transcript_dir = project_dir / "agent-transcripts"
            if not transcript_dir.is_dir():
                continue
            for session in list_session_files(
                transcript_dir,
                min_size_kb=min_size_kb,
                pattern="*/*.jsonl",
            ):
                session["cursor_project_dir"] = str(project_dir)
                sessions.append(session)

        ordered = sorted(sessions, key=self._session_sort_key, reverse=True)
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
        turns = parse_cursor_jsonl_session(
            session_path,
            issues=issues,
        )

        lines = [f"# Cursor Session: {session_id}"]
        for i, turn in enumerate(turns, 1):
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user']}")
            if turn.get("assistant"):
                for resp in turn["assistant"]:
                    lines.append(f"\nAssistant: {resp}")
            if turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"]]
                lines.append(f"\nTools: {', '.join(tool_names)}")

        raw_content = "\n".join(lines)

        metadata: dict[str, Any] = {
            "project_name": project_name,
            "cursor_projects_dir": str(self.projects_dir),
        }
        if self.project_root is not None:
            metadata["project_root"] = str(self.project_root)

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="cursor",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata=metadata,
            tags=["session", "cursor"],
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
                "CursorAdapter.sync_session requires an initialized backend"
            )
        native_bytes = session_path.read_bytes()
        source_text = native_bytes.decode("utf-8-sig", errors="replace")
        observation = self.session_to_observation(
            session_path,
            session_id,
            project_name,
            issues=issues,
        )
        project_root = self.project_root or Path.cwd()
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(project_root),
            client="cursor",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=source_uri_from_path(session_path),
            source_text=source_text,
            raw_bytes=native_bytes,
            mtime_ns=session_path.stat().st_mtime_ns,
            sequence_count=len(source_text.splitlines()),
            parser_version="cursor-jsonl-v1",
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
            issues=warnings,
        )

        if self.backend is None:
            raise RuntimeError("CursorAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Cursor ingest")

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
            client="cursor",
            source_root=self.projects_dir,
            sessions=sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            self._append_issue(
                warnings,
                level="error",
                code="session_ingest_failed",
                message=f"Failed to ingest Cursor session {session_id}: {failure.error}",
                path=failure.session["path"],
                session_id=session_id,
            )

        return {
            "project_name": project_name,
            "sessions_found": len(sessions),
            "sessions_scanned": scan.sessions_scanned,
            "ingested": scan.ingested,
            "updated": scan.updated,
            "unchanged": scan.unchanged,
            "errors": len(scan.failures),
            "scan_frontier": scan.frontier.to_dict(),
            "warnings": warnings,
        }

    def _matching_project_dirs(
        self, *, issues: list[Issue] | None = None
    ) -> list[Path]:
        all_dirs = [
            path
            for path in self.projects_dir.iterdir()
            if path.is_dir() and (path / "agent-transcripts").is_dir()
        ]
        if self.project_root is None:
            return all_dirs

        target_root = self.project_root
        candidate_names = {
            _normalize_token(value)
            for value in cursor_project_name_candidates_from_path(
                self.project_root_text or target_root
            )
        }
        matched = [
            path for path in all_dirs if _normalize_token(path.name) in candidate_names
        ]
        if matched:
            return matched

        fallback_matches: list[Path] = []
        for project_dir in all_dirs:
            if self._project_dir_mentions_root(
                project_dir,
                target_root,
                root_text=self.project_root_text,
            ):
                fallback_matches.append(project_dir)
        if fallback_matches:
            return fallback_matches

        self._append_issue(
            issues,
            level="warning",
            code="cursor_project_not_found",
            message=f"No Cursor project directory matched workspace root {target_root}",
            path=target_root,
        )
        return []

    @staticmethod
    def _project_dir_mentions_root(
        project_dir: Path,
        project_root: Path,
        *,
        root_text: str | None = None,
    ) -> bool:
        native_text = root_text or str(project_root)
        variants = _cursor_path_variants(root_text=native_text)
        transcript_dir = project_dir / "agent-transcripts"
        for session_file in transcript_dir.glob("*/*.jsonl"):
            try:
                text = session_file.read_text(
                    encoding="utf-8-sig", errors="replace"
                ).lower()
            except OSError:
                continue
            if any(variant in text for variant in variants):
                return True
        return False

    @staticmethod
    def _session_sort_key(session: SessionRecord) -> datetime:
        return session_sort_key(session)

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


def cursor_project_name_candidates_from_path(path: Path | str) -> list[str]:
    drive, parts = _cursor_path_parts(path)
    root_name = parts[-1] if parts else Path(str(path)).name
    safe_parts = [
        re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-")
        for part in parts
        if part not in {"\\", "/"} and part.strip("\\/")
    ]
    slug = "-".join(part for part in safe_parts if part)

    candidates = [root_name]
    if drive and slug:
        candidates.append(f"{drive}-{slug}")
    elif slug:
        candidates.append(slug)

    if drive and root_name:
        candidates.append(f"{drive}-{root_name}")

    unique: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip("-")
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _normalize_cursor_project_root(path: Path) -> Path:
    raw = str(path)
    if _looks_like_windows_absolute_path(raw):
        return path
    return normalize_project_root(path.expanduser())


def _looks_like_windows_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _cursor_path_parts(path: Path | str) -> tuple[str, list[str]]:
    raw = str(path).strip()
    if _looks_like_windows_absolute_path(raw):
        normalized = raw.replace("\\", "/")
        drive = normalized[0].lower()
        suffix = normalized[2:].lstrip("/")
        parts = [part for part in suffix.split("/") if part]
        return drive, parts

    root = normalize_project_root(Path(raw).expanduser())
    resolved = root.expanduser().resolve()
    drive = resolved.drive.rstrip(":").lower()
    parts = list(resolved.parts)
    if drive and parts:
        parts = parts[1:]
    cleaned_parts = [
        part for part in parts if part not in {"\\", "/"} and part.strip("\\/")
    ]
    return drive, cleaned_parts


def _cursor_path_variants(*, root_text: str) -> set[str]:
    normalized = root_text.replace("\\", "/").strip()
    variants = {
        root_text.lower(),
        root_text.replace("\\", "\\\\").lower(),
        normalized.lower(),
    }
    if _looks_like_windows_absolute_path(root_text):
        variants.add(root_text.replace("/", "\\").lower())
        variants.add(root_text.replace("/", "\\\\").lower())
    return {variant for variant in variants if variant}
