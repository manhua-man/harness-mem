"""Read exact native Codex turn provenance without starting or changing a host."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class NativeCodexTurn:
    status: Literal["heartbeat", "ordinary", "pending", "unknown"]
    turn_id: str | None = None
    binding_sha256: str | None = None
    heartbeat_at: float | None = None
    completed: bool = False


def read_native_codex_turn(
    native_transcript_path: str | Path, *, session_id: str,
    project_root: str | Path, turn_id: str | None = None,
) -> NativeCodexTurn:
    """Classify only the latest independently bound lifecycle and native users.

    A context-only prefix is pending, not proof of automatic origin. Exact
    lifecycle/header identity yields a stable binding while later message bytes
    append. Any newer lifecycle invalidates a caller's older requested turn.
    """
    unknown = NativeCodexTurn("unknown")
    if not isinstance(session_id, str) or not session_id or (
        turn_id is not None and (not isinstance(turn_id, str) or not turn_id)
    ):
        return unknown
    header = None
    current = None
    anchor = None
    heartbeat_seen = False
    heartbeat_at = None
    ordinary_seen = False
    orphan_user = False
    completed = False
    try:
        path = Path(native_transcript_path)
        if not path.is_absolute():
            return unknown
        path = path.resolve(strict=True)
        project = Path(project_root).resolve(strict=False)
        with path.open(encoding="utf-8-sig") as transcript:
            for line in transcript:
                record = json.loads(line)
                if not isinstance(record, dict):
                    return unknown
                record_type = record.get("type")
                native = record.get("payload")
                if not isinstance(native, dict):
                    if record_type in {"session_meta", "turn_context", "response_item", "event_msg"}:
                        return unknown
                    continue
                if record_type == "session_meta":
                    cwd = native.get("cwd")
                    if (native.get("id") != session_id
                            or native.get("session_id", session_id) != session_id
                            or not isinstance(cwd, str) or not cwd
                            or Path(cwd).resolve(strict=False) != project):
                        return unknown
                    if header is not None and native != header:
                        return unknown
                    header = native
                    continue
                lifecycle = record_type == "turn_context" or (
                    record_type == "event_msg" and native.get("type") == "task_started"
                )
                if lifecycle:
                    if header is None:
                        return unknown
                    identity = native.get("turn_id")
                    attribution = native.get("turn_attribution")
                    if (not isinstance(identity, str) or not identity
                            or (attribution is not None and (
                                not isinstance(attribution, dict)
                                or attribution.get("turn_id") != identity))):
                        return unknown
                    if identity != current:
                        current = identity
                        anchor = record
                        heartbeat_seen = False
                        heartbeat_at = None
                        ordinary_seen = orphan_user
                        orphan_user = False
                        completed = False
                    continue
                if (record_type == "event_msg" and native.get("type") == "task_complete"
                        and native.get("turn_id") == current):
                    completed = True
                    continue
                if record_type == "response_item" and native.get("type") != "message" and (
                    native.get("role") == "user" or record.get("role") == "user"
                ):
                    return unknown
                if record_type != "response_item" or native.get("type") != "message":
                    continue
                role = native.get("role")
                if role not in {"user", "assistant", "developer", "system", "tool"}:
                    return unknown
                if record.get("role", role) != role:
                    return unknown
                metadata = native.get("internal_chat_message_metadata_passthrough")
                metadata = metadata if isinstance(metadata, dict) else {}
                kinds = metadata.get("content_item_kinds")
                if role != "user":
                    # A non-user role cannot establish user origin by copying
                    # native-looking metadata or labels inside its own prose.
                    if isinstance(kinds, list) and "user.heartbeat" in kinds:
                        return unknown
                    continue
                bound = current is not None and metadata.get("turn_id") == current
                if bound and kinds in (["environments.environment_context"], ["agents_md.instructions"]):
                    continue
                if not bound:
                    ordinary_seen = True
                    orphan_user = True
                    continue
                content = native.get("content")
                nonempty = isinstance(content, list) and any(
                    isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]
                    for item in content
                )
                if kinds == ["user.heartbeat"] and nonempty:
                    if not heartbeat_seen:
                        stamp = record.get("timestamp")
                        try:
                            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
                            heartbeat_at = parsed.timestamp() if parsed is not None and parsed.tzinfo is not None else None
                        except (ValueError, OverflowError, OSError):
                            heartbeat_at = None
                    heartbeat_seen = True
                else:
                    ordinary_seen = True
    except (OSError, ValueError, TypeError, UnicodeError):
        return unknown
    if header is None or current is None or anchor is None or (turn_id is not None and turn_id != current):
        return unknown
    binding = hashlib.sha256(json.dumps({
        "path": str(path), "session_id": session_id, "project_root": str(project),
        "header": header, "lifecycle": anchor,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return NativeCodexTurn(
        "ordinary" if ordinary_seen else "heartbeat" if heartbeat_seen else "pending",
        current, binding, heartbeat_at, completed,
    )
