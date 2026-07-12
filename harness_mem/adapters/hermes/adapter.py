"""Hermes adapter — ingest Hermes session JSON transcripts into harness-mem."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.parser import (
    parse_hermes_json_session,
    read_hermes_session_id,
    session_sort_key,
)
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

DEFAULT_SESSIONS_DIR = Path.home() / ".hermes" / "sessions"


class HermesAdapter:
    """Adapter for ingesting Hermes ``session_*.json`` transcripts."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        *,
        project_root: Path | None = None,
        scope: str = "project",
    ) -> None:
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
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
        if not self.sessions_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_missing",
                message=f"Hermes sessions directory does not exist: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []

        all_sessions = self._all_session_records(
            min_size_kb=min_size_kb,
            issues=issues,
        )

        scoped_sessions = [
            session
            for session in all_sessions
            if self._session_matches_scope(Path(session["path"]))
        ]
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
        turns = parse_hermes_json_session(session_path, issues=issues)

        lines = [f"# Hermes Session: {session_id}"]
        display_turns = self._select_observation_turns(turns, max_turns=20)
        for i, turn in display_turns:
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for response in turn["assistant"][:3]:
                    lines.append(f"\nAssistant: {response[:500]}")
            if turn.get("tools"):
                tool_names = [tool["name"] for tool in turn["tools"][:5]]
                lines.append(f"\nTools: {', '.join(tool_names)}")
            if i == 10 and len(turns) > 20:
                omitted = len(turns) - 20
                lines.append(f"\n[... {omitted} middle turns omitted ...]")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

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
            timestamp=datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc),
            metadata=metadata,
            tags=["session", "hermes"],
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
        scoped_sessions = [
            session
            for session in all_sessions
            if self._session_matches_scope(Path(session["path"]))
        ]
        scoped_sessions = sorted(scoped_sessions, key=session_sort_key, reverse=True)
        sessions = scoped_sessions[:limit]

        ingested = 0
        errors = 0
        skipped_existing = 0
        error_details: list[Issue] = []
        if self.backend is None:
            raise RuntimeError("HermesAdapter.ingest requires an initialized backend")

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
                issue: Issue = {
                    "level": "error",
                    "code": "session_ingest_failed",
                    "message": f"Failed to ingest Hermes session {session_id}: {exc}",
                    "path": str(session["path"]),
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
            "candidate_sessions": len(sessions),
            "ingested": ingested,
            "skipped_existing": skipped_existing,
            "errors": errors,
            "error_details": error_details,
            "warnings": warnings,
        }

    async def _existing_session_ids(self, project_name: str | None) -> set[str]:
        if self.backend is None:
            return set()
        observations = await self.backend.verbatim_store.list(limit=100000)
        return {
            observation.session_id
            for observation in observations
            if observation.client == "hermes"
            and (project_name is None or observation.metadata.get("project_name") == project_name)
        }

    def _all_session_records(
        self,
        *,
        min_size_kb: int,
        issues: list[Issue] | None,
    ) -> list[SessionRecord]:
        if not self.sessions_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_missing",
                message=f"Hermes sessions directory does not exist: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []

        records: list[SessionRecord] = []
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
            records.append(
                {
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
                }
            )
        return records

    def _session_matches_scope(self, session_path: Path) -> bool:
        if self.scope == "all" or self.project_root is None:
            return True
        variants = _project_root_variants(self.project_root)
        try:
            text = session_path.read_text(encoding="utf-8-sig", errors="replace").lower()
        except OSError:
            return False
        return any(variant in text for variant in variants)

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


__all__ = ["DEFAULT_SESSIONS_DIR", "HermesAdapter"]
