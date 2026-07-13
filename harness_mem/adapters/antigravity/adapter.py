"""Read Antigravity's local brain transcript JSONL files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

DEFAULT_BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"


class AntigravityAdapter:
    """Adapter for ``.gemini/antigravity/brain/*/transcript.jsonl``."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        brain_dir: Path | None = None,
        *,
        home_dir: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        home = Path.home() if home_dir is None else home_dir
        self.brain_dir = brain_dir or home / ".gemini" / "antigravity" / "brain"
        self.project_root = (
            normalize_project_root(project_root.expanduser())
            if project_root is not None
            else None
        )

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name, min_size_kb
        if not self.brain_dir.exists():
            return []
        sessions: list[SessionRecord] = []
        for path in self.brain_dir.glob("*/.system_generated/logs/transcript.jsonl"):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if self.project_root is not None and not self._transcript_matches(path, issues):
                continue
            session_id = path.parents[2].name
            sessions.append(
                {
                    "path": path,
                    "name": path.name,
                    "session_id": session_id,
                    "size_kb": path.stat().st_size / 1024,
                    "size_bytes": path.stat().st_size,
                    "size": f"{path.stat().st_size / 1024:.1f}KB",
                    "lines": sum(1 for _ in path.open(encoding="utf-8-sig", errors="replace")),
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                    "mtime_ns": path.stat().st_mtime_ns,
                }
            )
        sessions.sort(key=lambda item: item.get("mtime_ns", 0), reverse=True)
        return sessions if limit is None else sessions[:limit]

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        del issues
        lines = [f"# Antigravity Session: {session_id}"]
        records = _read_records(session_path)
        for record in records:
            record_type = str(record.get("type") or "")
            source = str(record.get("source") or "")
            content = record.get("content")
            if isinstance(content, str) and content.strip():
                label = "User" if record_type == "USER_INPUT" else source.title() or record_type.title()
                lines.append(f"\n{label}: {content[:4000]}")
            for tool_call in record.get("tool_calls") or []:
                if isinstance(tool_call, dict) and tool_call.get("name"):
                    lines.append(f"\nTool: {tool_call['name']} {str(tool_call.get('args') or '')[:1000]}")

        raw_content = "\n".join(lines)
        timestamp = datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc)
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="antigravity",
            raw_content=raw_content[:50000],
            content_type="transcript",
            timestamp=timestamp,
            metadata={
                "project_name": project_name,
                "project_root": str(self.project_root) if self.project_root else None,
                "antigravity_brain_dir": str(self.brain_dir),
                "antigravity_transcript": str(session_path),
            },
            tags=["session", "antigravity"],
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("AntigravityAdapter.ingest requires an initialized backend")
        sessions = self.list_sessions(project_name, min_size_kb=min_size_kb, limit=limit)
        existing = {
            item.session_id
            for item in await self.backend.verbatim_store.list(limit=100000)
            if item.client == "antigravity"
            and (project_name is None or item.metadata.get("project_name") == project_name)
        }
        ingested = 0
        skipped = 0
        errors: list[Issue] = []
        for session in sessions:
            session_id = str(session["session_id"])
            if session_id in existing:
                skipped += 1
                continue
            try:
                await self.backend.verbatim_store.save(
                    self.session_to_observation(session["path"], session_id, project_name)
                )
                existing.add(session_id)
                ingested += 1
            except Exception as exc:  # noqa: BLE001 - report one session and continue
                errors.append({
                    "level": "error",
                    "code": "session_ingest_failed",
                    "message": f"Failed to ingest Antigravity session {session_id}: {exc}",
                    "path": str(session["path"]),
                    "session_id": session_id,
                })
        return {
            "project_name": project_name,
            "project_root": str(self.project_root) if self.project_root else None,
            "sessions_found": len(sessions),
            "candidate_sessions": len(sessions),
            "ingested": ingested,
            "skipped_existing": skipped,
            "errors": len(errors),
            "error_details": errors,
        }

    def _transcript_matches(self, path: Path, issues: list[Issue] | None) -> bool:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            if issues is not None:
                issues.append({"level": "warning", "code": "transcript_unreadable", "message": str(exc), "path": str(path)})
            return False
        lowered = text.lower().replace("/", "\\").replace("\\\\", "\\")
        return any(variant.replace("/", "\\") in lowered for variant in _path_variants(self.project_root))


def _read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _path_variants(path: Path | None) -> set[str]:
    if path is None:
        return set()
    value = str(path).replace("/", "\\").rstrip("\\").lower()
    return {value, value.replace("\\", "/")}


__all__ = ["DEFAULT_BRAIN_DIR", "AntigravityAdapter"]
