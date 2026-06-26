"""Concrete source adapters for common session JSONL clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import RawSession, SessionSource, SessionSpan


class JsonlSourceAdapter:
    """Base adapter for clients that store one JSON object per line."""

    name = "generic"

    def __init__(
        self,
        root: Path,
        *,
        project_name: str | None = None,
        pattern: str = "*.jsonl",
        recursive: bool = False,
    ) -> None:
        self.root = Path(root)
        self.project_name = project_name
        self.pattern = pattern
        self.recursive = recursive

    def discover(self, project: str | None = None) -> list[SessionSource]:
        if not self.root.is_dir():
            return []

        paths = self.root.rglob(self.pattern) if self.recursive else self.root.glob(self.pattern)
        sources: list[SessionSource] = []
        for path in sorted(paths):
            if not path.is_file():
                continue
            metadata = self._discover_metadata(path)
            session_id = str(metadata.get("session_id") or path.stem)
            project_for_source = self._source_project_name(path, metadata, project)
            if project and not self._matches_project(project, metadata, project_for_source):
                continue
            sources.append(
                SessionSource(
                    session_id=session_id,
                    path=path,
                    client=self.name,
                    project_name=project_for_source,
                    metadata=metadata,
                )
            )
        return sources

    def read_span(self, source: SessionSource, span: SessionSpan) -> RawSession:
        records, invalid_json_lines = _read_jsonl_records(source.path)
        text_items: list[str] = []
        compaction_events = 0
        orphan_tool_results = 0

        for record in records:
            if _is_compaction_event(record):
                compaction_events += 1
            orphan_tool_results += _orphan_tool_result_count(record)
            text_items.extend(self._record_text_items(record))

        end_turn = span.end_turn if span.end_turn is not None else len(text_items)
        selected = text_items[span.start_turn : end_turn]
        metadata = {
            **source.metadata,
            "client": self.name,
            "compaction_events": compaction_events,
            "invalid_json_lines": invalid_json_lines,
            "orphan_tool_results": orphan_tool_results,
            "records_read": len(records),
        }
        return RawSession(source=source, text="\n".join(selected).strip(), metadata=metadata)

    def build_packet_context(self, source: SessionSource) -> dict[str, object]:
        context: dict[str, object] = {
            "client": self.name,
            "source_path": str(source.path),
        }
        if source.project_name:
            context["project_name"] = source.project_name
        for key in ("cwd", "workspace_root", "thread_id", "session_id"):
            if key in source.metadata:
                context[key] = source.metadata[key]
        return context

    def _discover_metadata(self, path: Path) -> dict[str, Any]:
        records, invalid_json_lines = _read_jsonl_records(path)
        metadata = self._metadata_from_records(records)
        metadata.update(
            {
                "file_name": path.name,
                "file_size_bytes": path.stat().st_size,
                "invalid_json_lines": invalid_json_lines,
            }
        )
        return metadata

    def _metadata_from_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for record in records:
            record_metadata = record.get("metadata")
            if isinstance(record_metadata, dict):
                metadata.update(
                    {
                        key: value
                        for key, value in record_metadata.items()
                        if isinstance(key, str) and _metadata_value_is_simple(value)
                    }
                )
            for key in (
                "cwd",
                "workspace_root",
                "project",
                "project_name",
                "session_id",
                "thread_id",
            ):
                value = record.get(key)
                if value is not None and _metadata_value_is_simple(value):
                    metadata.setdefault(key, value)
        return metadata

    def _source_project_name(
        self,
        path: Path,
        metadata: dict[str, Any],
        requested_project: str | None,
    ) -> str | None:
        value = metadata.get("project_name") or metadata.get("project")
        if isinstance(value, str) and value:
            return value
        if requested_project:
            return requested_project
        if self.project_name:
            return self.project_name
        return path.parent.name or None

    def _matches_project(
        self,
        project: str,
        metadata: dict[str, Any],
        project_name: str | None,
    ) -> bool:
        candidates = [
            project_name,
            metadata.get("project_name"),
            metadata.get("project"),
            metadata.get("cwd"),
            metadata.get("workspace_root"),
        ]
        normalized_project = _normalize_project_token(project)
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            normalized_candidate = _normalize_project_token(candidate)
            if (
                normalized_candidate == normalized_project
                or normalized_candidate.endswith("/" + normalized_project)
                or normalized_project in normalized_candidate.split("/")
            ):
                return True
        return False

    def _record_text_items(self, record: dict[str, Any]) -> list[str]:
        extracted = _extract_role_and_content(record)
        if extracted is None:
            return []
        role, content = extracted
        rendered = _render_content(content)
        if not rendered:
            return []
        return [f"{role}: {rendered}"]


class ClaudeSourceAdapter(JsonlSourceAdapter):
    """Adapter for Claude Code JSONL sessions."""

    name = "claude"


class CodexSourceAdapter(JsonlSourceAdapter):
    """Adapter for Codex rollout/archive JSONL sessions."""

    name = "codex"

    def _metadata_from_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        metadata = super()._metadata_from_records(records)
        for record in records:
            payload = record.get("payload")
            if isinstance(payload, dict):
                for key in ("cwd", "workspace_root", "session_id", "thread_id"):
                    value = payload.get(key)
                    if value is not None and _metadata_value_is_simple(value):
                        metadata.setdefault(key, value)
        return metadata


class GenericJsonlSourceAdapter(JsonlSourceAdapter):
    """Adapter for generic agent JSONL records with role/content fields."""

    name = "generic"


def _read_jsonl_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    invalid_json_lines = 0
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            invalid_json_lines += 1
            continue
        if isinstance(record, dict):
            records.append(record)
    return records, invalid_json_lines


def _extract_role_and_content(record: dict[str, Any]) -> tuple[str, Any] | None:
    role = record.get("role")
    if isinstance(role, str) and "content" in record:
        return role, record.get("content")

    message = record.get("message")
    if isinstance(message, dict):
        message_role = message.get("role")
        if isinstance(message_role, str) and "content" in message:
            return message_role, message.get("content")

    record_type = record.get("type")
    if record_type in {"user", "assistant", "system"}:
        if isinstance(message, dict):
            return str(record_type), message.get("content", "")
        if "content" in record:
            return str(record_type), record.get("content")

    event = record.get("event")
    if isinstance(event, str):
        role_from_event = _role_from_event(event)
        if role_from_event:
            return role_from_event, record.get("content") or record.get("text") or message

    payload = record.get("payload")
    if isinstance(payload, dict):
        payload_role = payload.get("role")
        if isinstance(payload_role, str) and "content" in payload:
            return payload_role, payload.get("content")

    return None


def _render_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "content", "message"):
            if key in content:
                rendered = _render_content(content[key])
                if rendered:
                    return rendered
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    rendered = _render_content(item.get("text"))
                elif item_type == "tool_use":
                    rendered = _render_tool_use(item)
                elif item_type == "tool_result":
                    rendered = _render_content(item.get("content"))
                else:
                    rendered = _render_content(item)
            else:
                rendered = _render_content(item)
            if rendered:
                parts.append(rendered)
        return "\n".join(parts)
    return str(content)


def _render_tool_use(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "tool")
    tool_input = item.get("input")
    if tool_input is None:
        return f"[tool:{name}]"
    return f"[tool:{name}] {json.dumps(tool_input, ensure_ascii=False, sort_keys=True)}"


def _role_from_event(event: str) -> str | None:
    normalized = event.lower().replace("-", "_")
    if normalized in {"user", "user_message", "message_user"}:
        return "user"
    if normalized in {"assistant", "assistant_message", "message_assistant"}:
        return "assistant"
    if normalized in {"system", "system_message"}:
        return "system"
    return None


def _is_compaction_event(record: dict[str, Any]) -> bool:
    return record.get("subtype") == "compact_boundary" or bool(record.get("compactMetadata"))


def _orphan_tool_result_count(record: dict[str, Any]) -> int:
    message = record.get("message")
    if not isinstance(message, dict):
        return 0
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        1
        for item in content
        if isinstance(item, dict) and item.get("type") == "tool_result"
    )


def _metadata_value_is_simple(value: Any) -> bool:
    return isinstance(value, str | int | float | bool)


def _normalize_project_token(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").split(":")[-1].lower()
