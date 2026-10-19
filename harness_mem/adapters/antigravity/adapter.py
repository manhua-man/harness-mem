"""Read Antigravity brain transcripts and CLI ``history.jsonl`` sessions."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from harness_mem.adapters.claude_code.project_profile_detector import normalize_project_root
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.scan_scheduler import sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult, persist_session_snapshot
from harness_mem.adapters.source_metadata import (
    metadata_record,
    read_jsonl_metadata,
    structured_metadata_roots,
)
from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.transcript_chunking import source_uri_from_path

DEFAULT_BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"
DEFAULT_CLI_ROOT = Path.home() / ".gemini" / "antigravity-cli"
DEFAULT_IDE_BRAIN_DIR = Path.home() / ".gemini" / "antigravity-ide" / "brain"


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
        self.ide_brain_dir = (
            (DEFAULT_IDE_BRAIN_DIR if home_dir is None else home / ".gemini" / "antigravity-ide" / "brain")
            if brain_dir is None else None
        )
        self.project_root = _normalize_workspace_path(project_root)
        self._discovered_roots: dict[tuple[Path, str], list[str]] = {}

    def _brain_dirs(self) -> tuple[Path, ...]:
        roots = [self.brain_dir]
        if self.cli_root is not None:
            roots.append(self.cli_root / "brain")
        if self.ide_brain_dir is not None:
            roots.append(self.ide_brain_dir)
        return tuple(dict.fromkeys(roots))

    def list_session_metadata(
        self,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """Discover identities without rendering or reading complete transcripts.

        History sizes count native selected rows plus the companion file's stat,
        not the size of a generated export. History is streamed once, retaining
        metadata only. A workspace conflict remains visible as unknown ownership.
        """
        history: dict[str, dict[str, Any]] = {}
        if self.history_file is not None and self.history_file.is_file():
            try:
                history = _history_metadata(self.history_file)
            except OSError as exc:
                _metadata_issue(issues, self.history_file, exc)

        sessions_by_id: dict[str, SessionRecord] = {}
        for brain in self._brain_dirs():
            for path in brain.glob("*/.system_generated/logs/transcript*.jsonl"):
                try:
                    if path.name not in {"transcript.jsonl", "transcript_full.jsonl"}:
                        continue
                    if path.name == "transcript.jsonl" and (
                        path.parent / "transcript_full.jsonl"
                    ).is_file():
                        continue
                    stat = path.stat()
                    if not path.is_file() or stat.st_size == 0:
                        continue
                    session_id = path.parents[2].name
                    # Exact native conversation membership, never a helper/path
                    # mention, can supply a brain transcript's discovery roots.
                    roots = list(history.get(session_id, {}).get("project_roots", []))
                    if not roots:
                        roots, _ = read_jsonl_metadata(path, client="antigravity")
                    record = metadata_record(
                        path, session_id, project_roots=roots, source_kind="brain-jsonl",
                    )
                    record["metadata_paths"] = self._source_metadata_paths(path, session_id)
                    _set_metadata_ownership(record, roots)
                    sessions_by_id[session_id] = record
                except OSError as exc:
                    _metadata_issue(issues, path, exc)

        for session_id, metadata in history.items():
            assert self.history_file is not None
            try:
                record = metadata_record(
                    self.history_file, session_id,
                    project_roots=metadata["project_roots"],
                    source_kind="antigravity-cli-session-export",
                )
                transcript = _find_cli_transcript(self.cli_root, session_id)
                record["metadata_paths"] = self._source_metadata_paths(self.history_file, session_id)
                transcript_stat = transcript.stat() if transcript is not None else None
                size_bytes = metadata["size_bytes"] + (
                    transcript_stat.st_size if transcript_stat is not None else 0
                )
                timestamp_ms = metadata["timestamp_ms"]
                record["size_bytes"] = size_bytes
                record["size_kb"] = size_bytes / 1024
                record["mtime_ns"] = max(
                    int(timestamp_ms * 1_000_000) if timestamp_ms else record["mtime_ns"],
                    transcript_stat.st_mtime_ns if transcript_stat is not None else 0,
                )
                record["mtime"] = datetime.fromtimestamp(
                    record["mtime_ns"] / 1_000_000_000, tz=timezone.utc,
                )
                _set_metadata_ownership(record, metadata["project_roots"])
                sessions_by_id[session_id] = record
            except OSError as exc:
                _metadata_issue(issues, self.history_file, exc)

        sessions = [
            record for record in sessions_by_id.values()
            if record["size_bytes"] / 1024 >= min_size_kb
        ]
        sessions.sort(key=lambda item: item["mtime_ns"], reverse=True)
        sessions = sessions if limit is None else sessions[:limit]
        self._discovered_roots = {
            (record["path"].resolve(strict=False), record["session_id"]):
            list(record["project_roots"])
            for record in sessions
        }
        return sessions

    def _source_metadata_paths(self, path: Path, session_id: str) -> list[Path]:
        """Dependencies for ephemeral previews, including attachment replacement.

        Directory stamps detect creation of a previously absent history or full
        transcript. They are cache invalidation hints, never ownership evidence.
        Only paths actually consulted by this adapter are dependencies; it does
        not infer ownership from arbitrary sidecars.
        """
        candidates = [path, path.parent]
        if self.history_file is not None:
            candidates.append(self.history_file)
        if self._is_history_file(path) and self.cli_root is not None and _safe_session_id(session_id):
            log_dir = self.cli_root / "brain" / session_id / ".system_generated" / "logs"
            candidates.extend(log_dir / name for name in ("transcript_full.jsonl", "transcript.jsonl"))
        dependencies: list[Path] = []
        for candidate in candidates:
            while not candidate.exists() and candidate != candidate.parent:
                candidate = candidate.parent
            if candidate.exists() and candidate not in dependencies:
                dependencies.append(candidate)
        return dependencies

    def read_session_source(self, session_path: Path, session_id: str, *, workspace_scoped: bool = True) -> dict[str, Any]:
        """Read one complete source and recheck reliable native membership.

        Discovery is only a hint. No cached history bodies or header budget is
        used for this read, and compatibility sync matching stays independent.
        """
        uri = source_uri_from_path(session_path)
        if self._is_history_file(session_path):
            exported = _history_export_for_session(
                session_path, session_id, cli_root=self.cli_root,
            )
            exported["source_uri"] = f"{uri}#conversation={quote(session_id, safe='')}"
        else:
            if not any(
                session_path.resolve(strict=False)
                == (brain / session_id / ".system_generated" / "logs" / name).resolve(strict=False)
                for brain in self._brain_dirs()
                for name in ("transcript_full.jsonl", "transcript.jsonl")
            ) or not _safe_session_id(session_id):
                raise ValueError("Antigravity source is outside known session locations")
            raw = session_path.read_bytes()
            text = raw.decode("utf-8-sig", errors="strict")
            history_roots: list[str] = []
            if self.history_file is not None and self.history_file.is_file():
                history_roots = _native_roots(_history_records_for_session(self.history_file, session_id))
            roots = [*history_roots, *_native_roots(_records_from_text(text), workspace_root=_single_native_root(history_roots))]
            exported = {
                "raw_bytes": raw, "source_text": text, "source_uri": uri,
                "project_roots": list(dict.fromkeys(roots)),
            }
        roots = exported["project_roots"]
        identities = {_metadata_root_identity(root) for root in roots}
        if workspace_scoped and len(identities) > 1:
            raise ValueError("Antigravity source has conflicting native workspace roots")
        discovered = self._discovered_roots.get((session_path.resolve(strict=False), session_id))
        if workspace_scoped and discovered and identities != {_metadata_root_identity(root) for root in discovered}:
            raise ValueError("Antigravity source workspace metadata changed after discovery")
        return exported

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
        paths = (
            path for brain in self._brain_dirs()
            for path in brain.glob("*/.system_generated/logs/transcript*.jsonl")
        )
        for path in paths:
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
            content = None
            for key in ("content", "text", "message", "display"):
                value = record.get(key)
                if isinstance(value, str) and value.strip():
                    content = value
                    break
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
        limit: int | None = None,
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
        records = _read_records(path)
        if any(
            _workspace_matches(workspace, self.project_root or "")
            for record in records
            for workspace in _workspace_values(record)
        ):
            return True
        lowered = text.lower().replace("/", "\\").replace("\\\\", "\\")
        return any(variant.replace("/", "\\") in lowered for variant in _path_variants(self.project_root))


def _read_records(path: Path) -> list[dict[str, Any]]:
    return _records_from_text(path.read_text(encoding="utf-8-sig", errors="replace"))


def _records_from_text(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
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
    records = _history_records_for_session(path, session_id)
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
    transcript_records = _records_from_text(transcript_bytes.decode("utf-8-sig", errors="replace"))
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
        "project_roots": list(dict.fromkeys([
            *_native_roots(records),
            *_native_roots(transcript_records, workspace_root=_single_native_root(_native_roots(records))),
        ])),
    }


def _history_records_for_session(path: Path, session_id: str) -> list[dict[str, Any]]:
    """Stream the shared container; retain only the exact selected conversation."""
    records: list[dict[str, Any]] = []
    for record, _ in _stream_history(path):
        if str(record.get("conversationId") or record.get("conversation_id") or "") == session_id:
            records.append(record)
    return records


def _stream_history(path: Path) -> Iterator[tuple[dict[str, Any], int]]:
    with path.open("rb") as stream:
        for line in stream:
            try:
                record = json.loads(line.decode("utf-8-sig", errors="replace"))
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record, len(line)


def _history_metadata(path: Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record, size_bytes in _stream_history(path):
        session_id = str(record.get("conversationId") or record.get("conversation_id") or "")
        if not session_id:
            continue
        metadata = grouped.setdefault(session_id, {
            "project_roots": [], "size_bytes": 0, "timestamp_ms": 0,
        })
        metadata["size_bytes"] += size_bytes
        metadata["project_roots"] = list(dict.fromkeys(
            [*metadata["project_roots"], *structured_metadata_roots(record)]
        ))
        timestamp = record.get("timestamp")
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            metadata["timestamp_ms"] = max(metadata["timestamp_ms"], int(timestamp))
    return grouped


def _single_native_root(roots: list[str]) -> str | None:
    identities = {_metadata_root_identity(root) for root in roots}
    return roots[0] if roots and len(identities) == 1 and "" not in identities else None


def _native_roots(records: list[dict[str, Any]], *, workspace_root: str | None = None) -> list[str]:
    return list(dict.fromkeys(
        root for record in records for root in structured_metadata_roots(record, workspace_root=workspace_root)
    ))


def _set_metadata_ownership(record: SessionRecord, roots: list[str]) -> None:
    record["project_roots"] = list(dict.fromkeys(roots))
    identities = {_metadata_root_identity(root) for root in roots}
    record["metadata_status"] = "available" if len(identities) == 1 and "" not in identities else "unknown"
    record.pop("cwd", None)
    if record["metadata_status"] == "available":
        record["cwd"] = roots[0]


def _metadata_issue(issues: list[Issue] | None, path: Path, exc: OSError) -> None:
    if issues is not None:
        issues.append({
            "level": "warning", "code": "session_metadata_unreadable",
            "message": str(exc), "path": str(path),
        })


def _metadata_root_identity(value: str) -> str:
    """Normalize local native identities without treating relative paths as owners."""
    if "://" in value:
        uri = urlsplit(value)
        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
            return ""
        value = unquote(uri.path)
        if len(value) > 2 and value[0] == "/" and value[2] == ":":
            value = value[1:]
    windows_path = bool(re.match(r"^[A-Za-z]:[\\/]", value))
    if not Path(value).is_absolute() and not windows_path:
        return ""
    normalized = _normalize_workspace_path(Path(value)) or value
    if windows_path:
        return normalized.replace("\\", "/").rstrip("/").casefold()
    return os.path.normcase(normalized).rstrip("\\/")


def _safe_session_id(session_id: str) -> bool:
    return bool(session_id and session_id not in {".", ".."} and not any(
        character in session_id for character in ("/", "\\", ":")
    ))


def _history_workspace(records: list[dict[str, Any]]) -> str:
    for record in records:
        value = record.get("workspace") or record.get("cwd")
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _workspace_values(value: object) -> list[str]:
    """Collect structured workspace identities from nested transcript records."""

    results: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if (
                key.casefold() in {"cwd", "workspace", "project_root"}
                and isinstance(nested, str)
                and nested.strip()
            ):
                results.append(nested)
            results.extend(_workspace_values(nested))
    elif isinstance(value, list):
        for nested in value:
            results.extend(_workspace_values(nested))
    return results


def _history_timestamp_ms(records: list[dict[str, Any]]) -> int | None:
    values = [
        int(record["timestamp"])
        for record in records
        if isinstance(record.get("timestamp"), (int, float))
        and record["timestamp"] > 0
    ]
    return max(values) if values else None


def _find_cli_transcript(cli_root: Path | None, session_id: str) -> Path | None:
    if cli_root is None or not _safe_session_id(session_id):
        return None
    log_dir = cli_root / "brain" / session_id / ".system_generated" / "logs"
    for name in ("transcript_full.jsonl", "transcript.jsonl"):
        candidate = log_dir / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def current_hook_task(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Read the latest native user step for this exact Hook conversation.

    This is bounded query context only, never a new source or saved knowledge.
    Ignore assistant, tool and injected messages, and never scan other sessions.
    """
    session_id = str(payload.get("conversationId") or "")
    raw_path = payload.get("transcriptPath")
    if not _safe_session_id(session_id) or not isinstance(raw_path, str):
        return None
    try:
        path = Path(raw_path).expanduser().resolve()
        allowed_roots = (DEFAULT_BRAIN_DIR, DEFAULT_CLI_ROOT / "brain", DEFAULT_IDE_BRAIN_DIR)
        expected = {
            (root / session_id / ".system_generated" / "logs" / name).resolve()
            for root in allowed_roots
            for name in ("transcript.jsonl", "transcript_full.jsonl")
        }
    except (OSError, ValueError):
        return None
    if path not in expected:
        return None
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - 262144)
            stream.seek(offset)
            if offset:
                stream.readline()  # Discard the possibly partial first record.
            records = _records_from_text(stream.read().decode("utf-8-sig", errors="replace"))
    except OSError:
        return None
    limit = payload.get("initialNumSteps")
    for record in reversed(records):
        if record.get("type") != "USER_INPUT":
            continue
        index = record.get("step_index")
        if isinstance(limit, int) and isinstance(index, int) and index >= limit:
            continue
        text = _record_text(record)
        if text:
            return text, str(index) if isinstance(index, int) else str(record.get("created_at") or "user")
        return None  # Do not reuse an older question when the latest user step is unreadable.
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
    normalized = _normalize_workspace_path(Path(value)) or value
    return normalized.replace("\\", "/").rstrip("/").casefold()


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
    if re.match(r"^[A-Za-z]:[\\/]", raw) and not Path(raw).is_absolute():
        return raw
    return str(normalize_project_root(Path(raw)))


def _path_variants(path: str | None) -> set[str]:
    if path is None:
        return set()
    value = str(path).replace("/", "\\").rstrip("\\").lower()
    return {value, value.replace("\\", "/")}


__all__ = ["DEFAULT_BRAIN_DIR", "DEFAULT_CLI_ROOT", "DEFAULT_IDE_BRAIN_DIR", "AntigravityAdapter"]
