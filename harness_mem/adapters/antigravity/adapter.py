"""Read Antigravity brain transcripts and CLI ``history.jsonl`` sessions."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"
DEFAULT_CLI_ROOT = Path.home() / ".gemini" / "antigravity-cli"


class AntigravityAdapter:
    """Adapter for Antigravity brain JSONL and CLI history exports."""

    def __init__(
        self,
        backend: MemoryBackend | None,
        brain_dir: Path | None = None,
        *,
        cli_root: Path | None = None,
        home_dir: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.backend = backend
        home = Path.home() if home_dir is None else home_dir
        self.brain_dir = brain_dir or (
            DEFAULT_BRAIN_DIR
            if home_dir is None
            else home / ".gemini" / "antigravity" / "brain"
        )
        self.cli_root = (
            cli_root
            if cli_root is not None
            else (
                DEFAULT_CLI_ROOT
                if home_dir is None
                else home / ".gemini" / "antigravity-cli"
            )
            if brain_dir is None
            else None
        )
        self.history_file = self.cli_root / "history.jsonl" if self.cli_root else None
        self.project_root = _normalize_workspace_path(project_root)

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        del project_name
        sessions_by_id: dict[str, SessionRecord] = {}
        for path in self.brain_dir.glob("*/.system_generated/logs/transcript*.jsonl"):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if path.name == "transcript.jsonl" and (
                path.parent / "transcript_full.jsonl"
            ).is_file():
                continue
            if path.stat().st_size / 1024 < min_size_kb:
                continue
            if self.project_root is not None and not self._transcript_matches(path, issues):
                continue
            session_id = path.parents[2].name
            sessions_by_id[session_id] = _file_session_record(
                path,
                session_id=session_id,
                source_kind="brain-jsonl",
            )
        if self.history_file is not None and self.history_file.is_file():
            for session_id, records in _history_sessions(self.history_file).items():
                workspace = _history_workspace(records)
                if self.project_root is not None and not _workspace_matches(
                    workspace,
                    self.project_root,
                ):
                    continue
                path = self.history_file
                exported = _history_export(
                    records,
                    transcript_path=_find_cli_transcript(self.cli_root, session_id),
                )
                size_bytes = len(exported["raw_bytes"])
                if size_bytes / 1024 < min_size_kb:
                    continue
                timestamp_ms = _history_timestamp_ms(records)
                record: SessionRecord = {
                    "path": path,
                    "name": str(records[-1].get("display") or session_id),
                    "session_id": session_id,
                    "size_kb": size_bytes / 1024,
                    "size_bytes": size_bytes,
                    "size": f"{size_bytes / 1024:.1f}KB",
                    "lines": len(records),
                    "mtime": _epoch_millis(timestamp_ms)
                    or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                    "mtime_ns": int(timestamp_ms * 1_000_000)
                    if timestamp_ms
                    else path.stat().st_mtime_ns,
                    "cwd": workspace,
                    "source_kind": "antigravity-cli-session-export",
                }
                sessions_by_id[session_id] = record
        sessions = list(sessions_by_id.values())
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
        if self._is_history_file(session_path):
            exported = _history_export_for_session(
                session_path,
                session_id,
                cli_root=self.cli_root,
            )
            return self._history_export_to_observation(
                exported,
                session_path,
                session_id,
                project_name,
            )
        lines = [f"# Antigravity Session: {session_id}"]
        records = _read_records(session_path)
        for record in records:
            record_type = str(record.get("type") or "")
            source = str(record.get("source") or "")
            content = next(
                (
                    record.get(key)
                    for key in ("content", "text", "message", "display")
                    if isinstance(record.get(key), str) and record.get(key).strip()
                ),
                None,
            )
            if isinstance(content, str) and content.strip():
                label = "User" if record_type == "USER_INPUT" else source.title() or record_type.title()
                lines.append(f"\n{label}: {content}")
            for tool_call in record.get("tool_calls") or []:
                if isinstance(tool_call, dict) and tool_call.get("name"):
                    lines.append(f"\nTool: {tool_call['name']} {str(tool_call.get('args') or '')}")

        raw_content = "\n".join(lines)
        timestamp = datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc)
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="antigravity",
            raw_content=raw_content,
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

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
        *,
        issues: list[Issue] | None = None,
    ) -> TranscriptSyncResult:
        """Capture one exact Antigravity source revision."""

        if self.backend is None:
            raise RuntimeError(
                "AntigravityAdapter.sync_session requires an initialized backend"
            )
        if self._is_history_file(session_path):
            exported = _history_export_for_session(
                session_path,
                session_id,
                cli_root=self.cli_root,
            )
            native_bytes = exported["raw_bytes"]
            source_text = exported["source_text"]
            observation = self._history_export_to_observation(
                exported,
                session_path,
                session_id,
                project_name,
            )
            timestamp_ms = _history_timestamp_ms(exported["records"])
            source_kind = "antigravity-cli-session-export"
            source_uri = (
                f"{source_uri_from_path(session_path)}#conversation="
                f"{quote(session_id, safe='')}"
            )
            mtime_ns = int(timestamp_ms * 1_000_000) if timestamp_ms else None
            sequence_count = len(exported["records"])
            parser_version = "antigravity-history-v1"
        else:
            native_bytes = session_path.read_bytes()
            source_text = native_bytes.decode("utf-8-sig", errors="replace")
            observation = self.session_to_observation(
                session_path,
                session_id,
                project_name,
                issues=issues,
            )
            stat_result = session_path.stat()
            source_kind = (
                "antigravity-cli-transcript"
                if self.cli_root is not None
                and _is_relative_to(session_path, self.cli_root)
                else "brain-jsonl"
            )
            source_uri = source_uri_from_path(session_path)
            mtime_ns = stat_result.st_mtime_ns
            sequence_count = source_text.count("\n") + int(bool(source_text))
            parser_version = "antigravity-jsonl-v2"
        return await persist_session_snapshot(
            self.backend,
            observation,
            project_name=project_name,
            project_root=str(self.project_root or Path.cwd()),
            client="antigravity",
            session_id=session_id,
            source_kind=source_kind,
            source_uri=source_uri,
            source_text=source_text,
            raw_bytes=native_bytes,
            mtime_ns=mtime_ns,
            sequence_count=sequence_count,
            parser_version=parser_version,
            reuse_logical_session=True,
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("AntigravityAdapter.ingest requires an initialized backend")
        if not project_name:
            raise ValueError("project_name is required for Antigravity ingest")
        sessions = self.list_sessions(project_name, min_size_kb=min_size_kb)
        errors: list[Issue] = []

        async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
            return await self.sync_session(
                session["path"],
                session["session_id"],
                project_name,
            )

        scan = await sync_sessions_fairly(
            self.backend.transcript_store,
            project_name=project_name,
            client="antigravity",
            source_root=self._source_root(),
            sessions=sessions,
            change_limit=limit,
            sync_session=sync_one,
        )
        for failure in scan.failures:
            session_id = failure.session["session_id"]
            errors.append({
                    "level": "error",
                    "code": "session_ingest_failed",
                    "message": f"Failed to ingest Antigravity session {session_id}: {failure.error}",
                    "path": str(failure.session["path"]),
                    "session_id": session_id,
                })
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

    def _is_history_file(self, path: Path) -> bool:
        return bool(
            self.history_file is not None
            and path.resolve(strict=False) == self.history_file.resolve(strict=False)
        )

    def _source_root(self) -> Path:
        if self.cli_root is not None:
            return self.cli_root.parent
        return self.brain_dir

    def _history_export_to_observation(
        self,
        exported: dict[str, Any],
        session_path: Path,
        session_id: str,
        project_name: str | None,
    ) -> Observation:
        records = exported["records"]
        lines = [f"# Antigravity Session: {session_id}"]
        workspace = _history_workspace(records)
        if workspace:
            lines.append(f"\nWorkspace: {workspace}")
        for record in records:
            display = record.get("display")
            if isinstance(display, str) and display.strip():
                lines.append(f"\nUser: {display}")
            response = record.get("response") or record.get("content")
            if isinstance(response, str) and response.strip():
                lines.append(f"\nAssistant: {response}")
        for record in exported.get("transcript_records", []):
            content = _record_text(record)
            if content:
                source = str(record.get("source") or record.get("type") or "Transcript")
                lines.append(f"\n{source.title()}: {content}")
        timestamp = _epoch_millis(_history_timestamp_ms(records)) or datetime.fromtimestamp(
            session_path.stat().st_mtime,
            tz=timezone.utc,
        )
        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="antigravity",
            raw_content="\n".join(lines),
            content_type="transcript",
            timestamp=timestamp,
            metadata={
                "project_name": project_name,
                "project_root": str(self.project_root or workspace or ""),
                "antigravity_history": str(session_path),
                "conversation_id": session_id,
            },
            tags=["session", "antigravity", "history"],
        )

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


def _file_session_record(
    path: Path,
    *,
    session_id: str,
    source_kind: str,
) -> SessionRecord:
    size_bytes = path.stat().st_size
    return {
        "path": path,
        "name": path.name,
        "session_id": session_id,
        "size_kb": size_bytes / 1024,
        "size_bytes": size_bytes,
        "size": f"{size_bytes / 1024:.1f}KB",
        "lines": sum(
            1 for _ in path.open(encoding="utf-8-sig", errors="replace")
        ),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        "mtime_ns": path.stat().st_mtime_ns,
        "source_kind": source_kind,
    }


def _history_sessions(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in _read_records(path):
        conversation_id = record.get("conversationId") or record.get(
            "conversation_id"
        )
        if conversation_id:
            grouped.setdefault(str(conversation_id), []).append(record)
    return grouped


def _history_export_for_session(
    path: Path,
    session_id: str,
    *,
    cli_root: Path | None,
) -> dict[str, Any]:
    records = _history_sessions(path).get(session_id)
    if not records:
        raise ValueError(f"Antigravity history session not found: {session_id}")
    return _history_export(
        records,
        transcript_path=_find_cli_transcript(cli_root, session_id),
    )


def _history_export(
    records: list[dict[str, Any]],
    *,
    transcript_path: Path | None = None,
) -> dict[str, Any]:
    session_id = str(
        records[0].get("conversationId") or records[0].get("conversation_id")
    )
    transcript_bytes = transcript_path.read_bytes() if transcript_path is not None else b""
    transcript_records = (
        _read_records(transcript_path) if transcript_path is not None else []
    )
    raw_export_records = [
        {
            "format": "harness-mem-antigravity-history-v1",
            "conversation_id": session_id,
            "transcript_name": transcript_path.name if transcript_path else None,
            "transcript_raw_base64": base64.b64encode(transcript_bytes).decode("ascii"),
        },
        *({"record": record} for record in records),
    ]
    normalized_records = [
        {
            "format": "harness-mem-antigravity-history-v1",
            "conversation_id": session_id,
        },
        *({"history_record": record} for record in records),
        *({"transcript_record": record} for record in transcript_records),
    ]
    raw_export_text = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in raw_export_records
    )
    source_text = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in normalized_records
    )
    return {
        "records": records,
        "transcript_records": transcript_records,
        "source_text": source_text,
        "raw_bytes": raw_export_text.encode("ascii"),
    }


def _history_workspace(records: list[dict[str, Any]]) -> str:
    for record in records:
        value = record.get("workspace") or record.get("cwd")
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _history_timestamp_ms(records: list[dict[str, Any]]) -> int | None:
    values = [
        int(record["timestamp"])
        for record in records
        if isinstance(record.get("timestamp"), (int, float))
        and record["timestamp"] > 0
    ]
    return max(values) if values else None


def _find_cli_transcript(cli_root: Path | None, session_id: str) -> Path | None:
    if cli_root is None:
        return None
    log_dir = cli_root / "brain" / session_id / ".system_generated" / "logs"
    for name in ("transcript_full.jsonl", "transcript.jsonl"):
        candidate = log_dir / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _record_text(record: dict[str, Any]) -> str:
    for key in ("content", "text", "message", "display"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _workspace_matches(workspace: str, project_root: str) -> bool:
    if not workspace:
        return False
    return _normalized_path(workspace) == _normalized_path(project_root) or _normalized_path(
        workspace
    ).startswith(_normalized_path(project_root) + "/")


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def _epoch_millis(value: int | None) -> datetime | None:
    if value is None or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _normalize_workspace_path(path: Path | None) -> str | None:
    if path is None:
        return None
    raw = str(path.expanduser())
    # Transcript metadata can contain a Windows workspace while the adapter is
    # inspected on a non-Windows machine (for example in CI). Do not resolve
    # that opaque identity against the host cwd.
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return raw
    return str(normalize_project_root(Path(raw)))


def _path_variants(path: str | None) -> set[str]:
    if path is None:
        return set()
    value = str(path).replace("/", "\\").rstrip("\\").lower()
    return {value, value.replace("\\", "/")}


__all__ = ["DEFAULT_BRAIN_DIR", "DEFAULT_CLI_ROOT", "AntigravityAdapter"]
