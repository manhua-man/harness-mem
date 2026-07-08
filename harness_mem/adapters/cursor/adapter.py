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
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

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
        self.project_root = normalize_project_root(project_root.expanduser()) if project_root is not None else None

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
        turns = parse_cursor_jsonl_session(session_path, issues=issues)

        lines = [f"# Cursor Session: {session_id}"]
        display_turns = self._select_observation_turns(turns, max_turns=20)
        for i, turn in display_turns:
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for resp in turn["assistant"][:3]:
                    lines.append(f"\nAssistant: {resp[:500]}")
            if turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"][:5]]
                lines.append(f"\nTools: {', '.join(tool_names)}")
            if i == 10 and len(turns) > 20:
                omitted = len(turns) - 20
                lines.append(f"\n[... {omitted} middle turns omitted ...]")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

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
            timestamp=datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc),
            metadata=metadata,
            tags=["session", "cursor"],
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
            raise RuntimeError("CursorAdapter.ingest requires an initialized backend")

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
                    message=f"Failed to ingest Cursor session {session_id}: {exc}",
                    path=session["path"],
                    session_id=session_id,
                )

        return {
            "project_name": project_name,
            "sessions_found": len(sessions),
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
            if observation.client == "cursor"
            and (project_name is None or observation.metadata.get("project_name") == project_name)
        }

    def _matching_project_dirs(self, *, issues: list[Issue] | None = None) -> list[Path]:
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
            for value in cursor_project_name_candidates_from_path(target_root)
        }
        matched = [
            path for path in all_dirs if _normalize_token(path.name) in candidate_names
        ]
        if matched:
            return matched

        fallback_matches: list[Path] = []
        for project_dir in all_dirs:
            if self._project_dir_mentions_root(project_dir, target_root):
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
    def _project_dir_mentions_root(project_dir: Path, project_root: Path) -> bool:
        native_text = str(project_root)
        variants = {
            native_text.lower(),
            native_text.replace("\\", "\\\\").lower(),
            project_root.as_posix().lower(),
        }
        transcript_dir = project_dir / "agent-transcripts"
        for session_file in transcript_dir.glob("*/*.jsonl"):
            try:
                text = session_file.read_text(encoding="utf-8-sig", errors="replace").lower()
            except OSError:
                continue
            if any(variant in text for variant in variants):
                return True
        return False

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


def cursor_project_name_candidates_from_path(path: Path) -> list[str]:
    root = normalize_project_root(path.expanduser())
    resolved = root.expanduser().resolve()
    drive = resolved.drive.rstrip(":").lower()
    parts = list(resolved.parts)
    if drive and parts:
        parts = parts[1:]
    safe_parts = [
        re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-")
        for part in parts
        if part not in {"\\", "/"} and part.strip("\\/")
    ]
    slug = "-".join(part for part in safe_parts if part)

    candidates = [root.name]
    if drive and slug:
        candidates.append(f"{drive}-{slug}")
    elif slug:
        candidates.append(slug)

    if drive and root.name:
        candidates.append(f"{drive}-{root.name}")

    unique: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip("-")
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
