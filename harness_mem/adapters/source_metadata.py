"""Small native metadata readers shared by host discovery adapters.

Discovery never renders a conversation or certifies its complete revision.
The byte budget applies only to finding structured header metadata; it must
never be used to truncate a selected source's later complete read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from harness_mem.adapters.protocol import SessionRecord


ROOT_FIELDS = ("cwd", "project_root", "workspace_root", "workspace")
HEADER_BYTES = 65536


def _local_metadata_path(value: str) -> Path | None:
    if "://" in value:
        uri = urlsplit(value)
        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
            return None
        value = unquote(uri.path)
        if os.name == "nt" and len(value) > 2 and value[0] == "/" and value[2] == ":":
            value = value[1:]
    path = Path(value)
    return path.resolve(strict=False) if path.is_absolute() else None


def structured_metadata_roots(value: dict[str, Any], *, workspace_root: str | None = None) -> list[str]:
    """Read only native metadata fields, never message text or tool arguments."""
    explicit = list(dict.fromkeys(
        item for key in ROOT_FIELDS[1:]
        if isinstance((item := value.get(key)), str) and item.strip()
    ))
    if workspace_root:
        explicit.append(workspace_root)
    explicit = list(dict.fromkeys(explicit))
    cwd = value.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return explicit
    # A native workspace/Git-root binding is stronger than its working directory.
    # Only corroborated child cwd is folded; different explicit roots conflict.
    paths = [_local_metadata_path(root) for root in explicit]
    candidate = _local_metadata_path(cwd)
    if explicit and candidate is not None and all(path is not None for path in paths):
        identities = {os.path.normcase(str(path)) for path in paths}
        if len(identities) == 1:
            owner = next(iter(identities))
            current = os.path.normcase(str(candidate))
            if current == owner or current.startswith(owner.rstrip("\\/") + os.sep):
                return explicit
    return list(dict.fromkeys([*explicit, cwd]))


def read_jsonl_metadata(
    path: Path, *, client: str, byte_budget: int = HEADER_BYTES, workspace_root: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Read complete header records within a bounded prefix, not the whole file."""
    stat = path.stat()
    roots, header = _read_jsonl_metadata(path.resolve(), client, byte_budget, stat.st_mtime_ns, stat.st_size, workspace_root)
    return list(roots), dict(header)


@lru_cache(maxsize=4096)
def _read_jsonl_metadata(
    path: Path, client: str, byte_budget: int, mtime_ns: int, size_bytes: int, workspace_root: str | None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    # Cache structured metadata only, not conversation text or raw prefixes.
    # Full admission still reads the complete selected native source independently.
    roots: list[str] = []
    header: dict[str, Any] = {}
    with path.open("rb") as stream:
        prefix = stream.read(byte_budget)
    # An incomplete final line is not a JSON record and cannot establish roots.
    lines = prefix.splitlines()
    if prefix and not prefix.endswith((b"\n", b"\r")) and size_bytes > len(prefix):
        lines = lines[:-1]
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8-sig", errors="strict"))
        except (UnicodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        metadata = record
        if client == "codex":
            if record.get("type") not in {"session_meta", "turn_context"}:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            metadata = payload
        if not header:
            header = {key: metadata[key] for key in (*ROOT_FIELDS, "id", "session_id", "timestamp")
                      if key in metadata and isinstance(metadata[key], (str, int, float))}
        roots.extend(structured_metadata_roots(metadata, workspace_root=workspace_root))
    return tuple(dict.fromkeys(roots)), header


def metadata_record(
    path: Path, session_id: str, *, project_roots: list[str],
    source_kind: str = "native", **extra: Any,
) -> SessionRecord:
    """Native metadata only: no digest, line count or semantic readability claim."""
    stat = path.stat()
    roots = list(dict.fromkeys(project_roots))
    return cast(SessionRecord, {
        **extra,
        "path": path,
        "session_id": session_id,
        "name": path.name,
        "size_kb": stat.st_size / 1024,
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        "mtime_ns": stat.st_mtime_ns,
        "source_kind": source_kind,
        "project_roots": roots,
        "metadata_status": "available" if roots else "unknown",
        **({"cwd": roots[0]} if len(roots) == 1 else {}),
    })
