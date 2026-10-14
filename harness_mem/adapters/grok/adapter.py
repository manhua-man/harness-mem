"""Grok adapter — ingest Grok CLI chat history into harness-mem."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import (
    normalize_project_root,
)
from harness_mem.adapters.parser import list_session_files, parse_grok_jsonl_session, session_sort_key
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.adapters.source_metadata import metadata_record, read_jsonl_metadata
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_SESSIONS_DIR = Path.home() / ".grok" / "sessions"


class GrokAdapter:
    """Adapter for ingesting Grok ``chat_history.jsonl`` transcripts."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        sessions_dir: Path | None = None,
        *,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self.project_root = (
            normalize_project_root(project_root.expanduser())
            if project_root is not None
            else None
        )

    def list_session_metadata(
        self, *, min_size_kb: int = 0, limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """Discover reversible full-path buckets and check native header roots."""
        sessions: list[SessionRecord] = []
        if not self.sessions_dir.is_dir():
            return sessions
        for project_dir in self._matching_project_dirs(issues=issues):
            decoded = unquote(project_dir.name)
            bucket_root = (
                decoded if Path(decoded).is_absolute()
                and quote(decoded, safe="") == project_dir.name else None
            )
            for path in project_dir.glob("*/chat_history.jsonl"):
                try:
                    if not path.is_file() or path.stat().st_size / 1024 < min_size_kb:
                        continue
                    roots, _ = read_jsonl_metadata(path, client="grok", workspace_root=bucket_root)
                    roots = list(dict.fromkeys(([bucket_root] if bucket_root else []) + roots))
                    record = metadata_record(
                        path, path.parent.name, project_roots=roots, source_kind="jsonl",
                        metadata_paths=[path],
                    )
                    if len(roots) != 1 or not Path(roots[0]).is_absolute():
                        record["metadata_status"] = "unknown"
                        record.pop("cwd", None)
                    if self.project_root is not None and (
                        record["metadata_status"] != "available"
                        or normalize_project_root(Path(roots[0])) != self.project_root
                    ):
                        continue
                    sessions.append(record)
                except OSError as exc:
                    self._append_issue(
                        issues, level="warning", code="session_scan_failed",
                        message=str(exc), path=path,
                    )
        ordered = sorted(sessions, key=session_sort_key, reverse=True)
        return ordered if limit is None else ordered[:limit]

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name
        if not self.sessions_dir.exists():
            self._append_issue(
                issues,
                level="warning",
                code="sessions_dir_missing",
                message=f"Grok sessions directory does not exist: {self.sessions_dir}",
                path=self.sessions_dir,
            )
            return []

        project_dirs = self._matching_project_dirs(issues=issues)
        sessions: list[SessionRecord] = []
        for project_dir in project_dirs:
            for record in list_session_files(project_dir, pattern="*/chat_history.jsonl",
                                             min_size_kb=min_size_kb, issues=issues):
                record["session_id"] = Path(record["path"]).parent.name
                sessions.append(record)

        ordered = sorted(sessions, key=session_sort_key, reverse=True)
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
        turns = parse_grok_jsonl_session(
            session_path,
            issues=issues,
        )

        lines = [f"# Grok Session: {session_id}"]
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
            "grok_sessions_dir": str(self.sessions_dir),
        }
        if self.project_root is not None:
            metadata["project_root"] = str(self.project_root)

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="grok",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata=metadata,
            tags=["session", "grok"],
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
                "GrokAdapter.sync_session requires an initialized backend"
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
            client="grok",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=source_uri_from_path(session_path),
            source_text=source_text,
            raw_bytes=native_bytes,
            mtime_ns=session_path.stat().st_mtime_ns,
            sequence_count=len(source_text.splitlines()),
            parser_version="grok-jsonl-v1",
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int | None = None,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        warnings: list[Issue] = []
        sessions = self.list_sessions(
            project_name=project_name,
            min_size_kb=min_size_kb,
            issues=warnings,
        )

        if self.backend is None:
            raise RuntimeError("GrokAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Grok ingest")

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
            client="grok",
            source_root=self.sessions_dir,
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
                message=f"Failed to ingest Grok session {session_id}: {failure.error}",
                path=failure.session["path"],
                session_id=session_id,
            )

        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "scope": "project" if self.project_root else "all",
            "sessions_found": len(sessions),
            "scoped_sessions": len(sessions),
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
        if self.project_root is None:
            return [path for path in self.sessions_dir.iterdir() if path.is_dir()]

        project_dir = self.sessions_dir / grok_project_bucket(self.project_root)
        if project_dir.is_dir():
            return [project_dir]

        self._append_issue(
            issues,
            level="warning",
            code="grok_project_not_found",
            message=f"No Grok project directory matched workspace root {self.project_root}",
            path=self.project_root,
        )
        return []

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


def grok_project_bucket(project_root: Path) -> str:
    """Return Grok's URL-encoded project-root bucket name."""

    return quote(str(project_root), safe="")


__all__ = ["DEFAULT_SESSIONS_DIR", "GrokAdapter", "grok_project_bucket"]
