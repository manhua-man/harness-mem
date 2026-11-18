"""Read the pre-SQLite OpenCode session tree without following source aliases."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn


class OpenCodeSourceError(ValueError):
    """A native-source failure with a reason safe to return in inventory."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class LegacyRows:
    session: dict[str, Any]
    messages: list[dict[str, Any]]
    parts: list[dict[str, Any]]
    files: dict[str, str]


def legacy_session_paths(storage: Path, session_id: str | None = None) -> list[Path]:
    root = storage / "session"
    if not root.is_dir() or root.resolve() != root.absolute():
        return []
    if session_id is None:
        candidates = root.glob("*/*.json")
    else:
        _require_id(session_id)
        candidates = root.glob(f"*/{session_id}.json")
    return sorted(path for path in candidates if path.is_file())


def legacy_session_info(path: Path, session_id: str) -> tuple[dict[str, Any], str]:
    info, digest = _read_object(path, session_id)
    if "projectID" in info and info["projectID"] != path.parent.name:
        raise OpenCodeSourceError("opencode_legacy_project_mismatch", session_id)
    directory = info.get("directory")
    if not isinstance(directory, str) or not Path(directory).is_absolute():
        raise OpenCodeSourceError("opencode_legacy_workspace_unknown", session_id)
    return info, digest


def legacy_dependencies(path: Path, session_id: str) -> list[Path]:
    """Collect files and membership directories without reading message bodies."""
    _require_id(session_id)
    storage = path.parents[2]
    messages = storage / "message" / session_id
    parts = storage / "part"
    files = [path, path.parent, path.parent.parent, messages.parent, messages, parts]
    for message in _json_members(messages):
        _require_id(message.stem)
        part_dir = parts / message.stem
        files.extend((message, part_dir, *_json_members(part_dir)))
    return files


def read_legacy_rows(path: Path, session_id: str) -> LegacyRows:
    storage = path.parents[2]
    info, digest = legacy_session_info(path, session_id)
    files = {path.relative_to(storage).as_posix(): digest}

    def read(member: Path) -> dict[str, Any]:
        value, digest = _read_object(member, member.stem)
        files[member.relative_to(storage).as_posix()] = digest
        return value

    message_paths = _json_members(storage / "message" / session_id)
    if not message_paths:
        raise OpenCodeSourceError("opencode_legacy_messages_missing", session_id)
    messages, parts = [], []
    seen_parts: set[str] = set()
    for message_path in message_paths:
        message = read(message_path)
        message_id = message["id"]
        if (message.get("sessionID", session_id) != session_id
                or not isinstance(message.get("role"), str) or not message["role"].strip()):
            raise OpenCodeSourceError("opencode_legacy_message_mismatch", message_id)
        messages.append({
            "id": message_id, "session_id": session_id,
            "time_created": _native_time(message, "created"), "data": message,
        })
        part_paths = _json_members(storage / "part" / message_id)
        if not part_paths:
            raise OpenCodeSourceError("opencode_legacy_parts_missing", message_id)
        for part_path in part_paths:
            part = read(part_path)
            part_id = part["id"]
            if (part.get("messageID") != message_id or part.get("sessionID", session_id) != session_id
                    or part_id in seen_parts or not isinstance(part.get("type"), str)
                    or not part["type"].strip()):
                raise OpenCodeSourceError("opencode_legacy_part_mismatch", part_id)
            seen_parts.add(part_id)
            parts.append({
                "id": part_id, "message_id": message_id, "session_id": session_id, "data": part,
            })
    messages.sort(key=lambda row: (row["time_created"] or 0, row["id"]))
    parts.sort(key=lambda row: (row["message_id"], row["id"]))
    return LegacyRows(
        {**info, "time_created": _native_time(info, "created"), "time_updated": _native_time(info, "updated")},
        messages, parts, files,
    )


def _native_time(value: dict[str, Any], field: str) -> int | float | None:
    time = value.get("time")
    stamp = time.get(field) if isinstance(time, dict) else None
    return stamp if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None


def _require_id(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", value) is None:
        raise OpenCodeSourceError("opencode_legacy_invalid_id")


def _json_members(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    if not directory.is_dir() or directory.resolve() != directory.absolute():
        raise OpenCodeSourceError("opencode_legacy_invalid_path", directory.name)
    return sorted(directory.glob("*.json"))


def _read_object(path: Path, expected_id: str) -> tuple[dict[str, Any], str]:
    _require_id(expected_id)
    try:
        if (path.resolve() != path.absolute() or not stat.S_ISREG(path.lstat().st_mode)
                or path.stem != expected_id):
            raise OpenCodeSourceError("opencode_legacy_invalid_path", path.name)
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys, parse_constant=_reject_constant,
        )
    except OpenCodeSourceError:
        raise
    except (OSError, ValueError, RecursionError) as exc:
        raise OpenCodeSourceError("opencode_legacy_invalid_json", path.name) from exc
    if not isinstance(value, dict) or value.get("id") != expected_id:
        raise OpenCodeSourceError("opencode_legacy_id_mismatch", path.name)
    return value, hashlib.sha256(raw).hexdigest()


def _unique_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("ambiguous JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")
