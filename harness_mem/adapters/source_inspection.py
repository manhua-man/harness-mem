"""Read-only native source discovery, ownership and conservative draft checks.

No backend is constructed here. Host exporters remain the owners of container
decoding; this module only joins their results into the inspection contract.
"""

from __future__ import annotations

import json
import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.parser import list_session_files
from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.capture_policy import decide_capture, redact_private_bytes, redact_private_text
from harness_mem.config.merge import MergedConfig
from harness_mem.transcript_chunking import sha256_bytes, source_uri_from_path

HOSTS = ("claude-code", "codex", "cursor", "grok", "hermes", "opencode", "antigravity")


@dataclass
class InspectedSource:
    client: str
    session_id: str
    source_uri: str
    native_digest: str
    text: str
    ownership: str
    readability: str
    reason: str | None
    record: SessionRecord
    adapter: Any


def normalized_root(value: str | Path) -> str:
    path = Path(value).expanduser()
    if not str(value).strip() or not path.is_absolute():
        return ""
    return os.path.normcase(str(path.resolve(strict=False))).rstrip("\\/")


def ownership_for(roots: list[str], project_root: Path) -> str:
    """Only structured local workspace metadata can establish ownership."""
    local: set[str] = set()
    for value in roots:
        if not value:
            continue
        if "://" in value:
            uri = urlsplit(value)
            if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
                return "unknown"
            value = unquote(uri.path)
            if os.name == "nt" and len(value) > 2 and value[0] == "/" and value[2] == ":":
                value = value[1:]
        path = Path(value)
        if not path.is_absolute():
            return "unknown"
        local.add(normalized_root(path))
    if len(local) != 1:
        return "unknown"
    target = normalized_root(project_root)
    owner = next(iter(local))
    return "project" if owner == target else "other"


def build_inspection_adapter(client: str, *, project_root: Path | None = None) -> Any:
    kwargs: dict[str, Any] = {}
    if client != "claude-code":
        kwargs["project_root"] = project_root
    if client in {"codex", "hermes"}:
        kwargs["scope"] = "all" if project_root is None else "project"
    return AdapterRegistry.build(client, None, **kwargs)


def list_native_records(adapter: Any, client: str, issues: list[Issue]) -> list[SessionRecord]:
    if client == "claude-code":
        return list_session_files(
            adapter.sessions_dir, pattern="*/*.jsonl", min_size_kb=0, issues=issues,
        )
    return adapter.list_sessions(min_size_kb=0, limit=None, issues=issues)


def _records(text: str, client: str) -> tuple[list[dict[str, Any]], str | None]:
    if not text.strip():
        return [], None
    try:
        if client == "hermes" and text.lstrip().startswith("{"):
            try:
                document = json.loads(text)
            except ValueError:
                document = None
            if isinstance(document, dict) and isinstance(document.get("messages"), list):
                return [document], None
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (ValueError, TypeError):
        return [], "parse_failed"
    if any(not isinstance(value, dict) for value in values):
        return [], "unknown_format"
    return values, None


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return value is not None and value is not False


def classify_records(records: list[dict[str, Any]], client: str) -> str:
    """Empty requires a recognized format with no interaction, never a size test."""
    if not records:
        return "empty_source"
    recognized = False
    interaction = False
    unknown = False
    for record in records:
        kind = str(record.get("type") or "")
        role = record.get("role")
        if client == "hermes" and isinstance(record.get("messages"), list):
            recognized = True
            interaction |= bool(record["messages"])
        elif record.get("format") in {
            "harness-mem-hermes-state-db-v1", "harness-mem-opencode-session-v1",
            "harness-mem-antigravity-history-v1",
        }:
            recognized = True
        elif record.get("table") in {"session", "sessions"} and isinstance(record.get("row"), dict):
            recognized = True
        elif record.get("table") in {"message", "messages", "part"} and isinstance(record.get("row"), dict):
            recognized = True
            interaction = True
        elif "history_record" in record or "transcript_record" in record:
            recognized = True
            interaction |= _has_content(record.get("history_record") or record.get("transcript_record"))
        elif client == "codex" and kind in {"session_meta", "turn_context"}:
            recognized = True
        elif client == "codex" and kind in {"response_item", "event_msg"}:
            recognized = True
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("type") in {
                "task_started", "task_complete", "token_count", "turn_aborted",
            }:
                continue
            interaction |= _has_content(payload)
        elif role in {"user", "assistant", "tool", "system"} or kind in {"user", "assistant"}:
            recognized = True
            message = record.get("message", record.get("content"))
            if isinstance(message, dict):
                message = message.get("content", message)
            interaction |= _has_content(message) or _has_content(record.get("tool_calls"))
        elif kind in {"turn_ended", "session_start", "session_end"}:
            recognized = True
        elif client == "antigravity" and kind in {"USER_INPUT", "AI_RESPONSE", "TOOL_CALL", "TOOL_RESULT"}:
            recognized = True
            interaction |= any(_has_content(record.get(key)) for key in ("content", "text", "message", "tool_calls"))
        else:
            unknown = True
    if unknown:
        return "unknown_format"
    if interaction:
        return "readable"
    return "empty_draft" if recognized else "unknown_format"


def structured_roots(records: list[dict[str, Any]], client: str) -> list[str]:
    roots: list[str] = []
    for record in records:
        metadata = record
        if client == "codex":
            if record.get("type") not in {"session_meta", "turn_context"}:
                continue
            metadata = record.get("payload") or {}
        if not isinstance(metadata, dict):
            continue
        # Do not inspect message content, tool arguments or textual path mentions.
        for key in ("cwd", "project_root", "workspace_root", "workspace"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                roots.append(value)
    return roots


def read_native_source(adapter: Any, client: str, record: SessionRecord) -> dict[str, Any]:
    """Reuse native exporters, never read a whole shared DB as one session."""
    path = Path(record["path"])
    session_id = record["session_id"]
    uri = source_uri_from_path(path)
    if client == "cursor" and callable(getattr(adapter, "read_session_source", None)):
        return adapter.read_session_source(path, session_id)
    if client == "codex":
        from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, render_codex_conversation
        raw = path.read_bytes()
        native_text = raw.decode("utf-8-sig", errors="strict")
        records, error = _records(native_text, client)
        roots = structured_roots(records, client)
        readability = error or classify_records(records, client)
        _, turns = parse_codex_archive_jsonl_session(path, content=native_text)
        text = render_codex_conversation(turns)
        # Match the existing permitted conversation capture, not host-private
        # system/context records or hidden reasoning from the rollout file.
        return {"raw_bytes": text.encode("utf-8"), "source_text": text,
                "source_uri": uri, "project_roots": roots,
                "readability": readability,
                "inspection_error": error or ("unknown_format" if readability == "unknown_format" else None)}
    if client == "hermes" and adapter._is_state_db(path):
        from harness_mem.adapters.hermes.adapter import _export_state_db_session
        exported = _export_state_db_session(path, session_id)
        return {**exported, "source_uri": f"{uri}#session={quote(session_id, safe='')}", "project_roots": [str(exported["session"].get("cwd") or record.get("cwd") or "")]}
    if client == "opencode":
        from harness_mem.adapters.opencode.adapter import _connect_readonly, _export_session
        with closing(_connect_readonly(path)) as db:
            opencode_export = _export_session(db, session_id)
        return {"raw_bytes": opencode_export.raw_bytes, "source_text": opencode_export.source_text, "source_uri": f"{uri}#session={quote(session_id, safe='')}", "project_roots": [str(opencode_export.session.get("directory") or "")]}
    if client == "antigravity" and adapter._is_history_file(path):
        from harness_mem.adapters.antigravity.adapter import _history_export_for_session
        exported = _history_export_for_session(path, session_id, cli_root=adapter.cli_root)
        return {**exported, "source_uri": f"{uri}#conversation={quote(session_id, safe='')}", "project_roots": structured_roots(exported["records"], client)}
    raw = path.read_bytes()
    return {"raw_bytes": raw, "source_text": raw.decode("utf-8-sig", errors="strict"), "source_uri": uri, "project_roots": []}


def inspect_native_source(
    adapter: Any, client: str, record: SessionRecord, *, project_root: Path, config: MergedConfig,
) -> InspectedSource:
    uri = source_uri_from_path(Path(record["path"]))
    session_id = record["session_id"]
    admitted = decide_capture(config, client=client, session_id=session_id, source_uri=uri)
    if not admitted.admitted:
        return InspectedSource(client, session_id, uri, "", "", "unknown", "excluded", admitted.reason, record, adapter)
    exported = read_native_source(adapter, client, record)
    uri = exported.get("source_uri", uri)
    text = exported["source_text"]
    records: list[dict[str, Any]]
    error: str | None
    if client == "codex":
        # Classification and ownership already used the complete native JSONL.
        # The permitted prose is deliberately not a JSON source, and must not
        # be parsed again or carry host-private records into inspection output.
        records, error = [], exported.get("inspection_error")
    else:
        records, error = _records(text, client)
    roots = list(exported.get("project_roots") or []) + structured_roots(records, client)
    if record.get("cwd"):
        roots.append(str(record["cwd"]))
    # Grok's URL-encoded full workspace bucket is a native identity, not a name.
    if client == "grok":
        bucket = Path(record["path"]).parent.parent.name
        decoded = unquote(bucket)
        if Path(decoded).is_absolute():
            roots.append(decoded)
    ownership = ownership_for(roots, project_root)
    status = exported.get("readability") or error or classify_records(records, client)
    if config.capture_private_tags:
        text, _ = redact_private_text(text)
        captured_bytes, _ = redact_private_bytes(exported["raw_bytes"])
    else:
        captured_bytes = exported["raw_bytes"]
    return InspectedSource(client, session_id, uri, sha256_bytes(captured_bytes), text, ownership, status, error, record, adapter)
