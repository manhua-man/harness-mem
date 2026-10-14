"""Project-scoped transcript admission and private-span redaction.

The capture policy runs before the immutable transcript ledger is written.  A
source excluded here never creates raw revisions, chunks, Observations, jobs,
or derived indexes.  ``<private>...</private>`` spans are replaced before both
the native-byte revision and normalized transcript are hashed.
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from harness_mem.config.merge import MergedConfig, load_merged_config

PRIVATE_REDACTION = "[private content omitted]"
_PRIVATE_TEXT_RE = re.compile(r"<private\b[^>]*>.*?</private\s*>", re.IGNORECASE | re.DOTALL)
_PRIVATE_BYTES_RE = re.compile(
    rb"<private\b[^>]*>.*?</private\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ANTIGRAVITY_EXPORT = "harness-mem-antigravity-history-v1"
_CAPTURE_JSON_DEPTH = 64


@dataclass(frozen=True)
class CaptureDecision:
    admitted: bool
    reason: str


def decide_capture(
    config: MergedConfig,
    *,
    client: str,
    session_id: str,
    source_uri: str,
) -> CaptureDecision:
    """Return whether a native source is admitted by the merged policy."""

    if not config.capture_enabled:
        return CaptureDecision(False, "capture_disabled")
    if client.casefold() in {value.casefold() for value in config.capture_ignore_clients}:
        return CaptureDecision(False, "client_ignored")
    if session_id in set(config.capture_ignore_session_ids):
        return CaptureDecision(False, "session_ignored")
    source_folded = source_uri.replace("\\", "/").casefold()
    if any(
        fnmatch.fnmatchcase(source_folded, pattern.replace("\\", "/").casefold())
        for pattern in config.capture_ignore_source_globs
    ):
        return CaptureDecision(False, "source_ignored")
    return CaptureDecision(True, "admitted")


def local_context_root(value: str) -> Path | None:
    """Normalize local paths/URIs without probing remote locations."""
    if not value or value.startswith(("\\\\", "//")):
        return None
    if "://" in value:
        uri = urlsplit(value)
        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
            return None
        value = unquote(uri.path)
        if os.name == "nt" and value.startswith("/") and value[2:3] == ":":
            value = value[1:]
    path = Path(value).expanduser()
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        return None
    return path.resolve(strict=False)


def source_capture_policy(project_roots: list[str], *, config_loader: Callable[..., MergedConfig] | None = None) -> MergedConfig:
    """Read existing local policy hints without requiring a source workspace.

    Missing or unknown contexts use user policy. For a multi-context session,
    every known local capture restriction applies; none grants broader access.
    This does not authorize background processing or create project profiles.
    """
    loader = config_loader or load_merged_config
    configs = [loader(None)]
    local_roots = {path for value in project_roots if (path := local_context_root(value)) is not None}
    for path in sorted(local_roots):
        if path.is_dir():
            configs.append(loader(path))
    return replace(
        configs[0], capture_enabled=all(config.capture_enabled for config in configs),
        capture_private_tags=any(config.capture_private_tags for config in configs),
        capture_ignore_clients=tuple(sorted({item for config in configs for item in config.capture_ignore_clients})),
        capture_ignore_session_ids=tuple(sorted({item for config in configs for item in config.capture_ignore_session_ids})),
        capture_ignore_source_globs=tuple(sorted({item for config in configs for item in config.capture_ignore_source_globs})),
    )


def redact_private_text(value: str) -> tuple[str, int]:
    """Remove private spans from normalized transcript text."""

    return _PRIVATE_TEXT_RE.subn(PRIVATE_REDACTION, value)


def redact_private_bytes(value: bytes) -> tuple[bytes, int]:
    """Redact native bytes, including the known Antigravity export attachment.

    Only that export's declared base64 field is decoded, once, with strict
    validation. Its decoded size cannot exceed the encoded input size; no
    decompression or recursive encoding discovery is performed. Unsupported or
    corrupt envelopes raise a content-free error before snapshot persistence.
    Public captures retain their exact bytes, including BOMs and line endings.
    """

    first = next((line for line in value.splitlines() if line.strip()), b"")
    try:
        header = json.loads(first.decode("utf-8-sig"))
    except (ValueError, UnicodeError, RecursionError):
        if b"harness-mem-antigravity-history-" in first or b"transcript_raw_" in first:
            raise ValueError("invalid encoded capture envelope") from None
    else:
        if isinstance(header, dict) and (
            str(header.get("format", "")).startswith("harness-mem-antigravity-history-")
            or any(key.casefold().startswith("transcript_raw") for key in header)
        ):
            if header.get("format") != _ANTIGRAVITY_EXPORT:
                raise ValueError("unsupported encoded capture envelope")
            return _redact_capture_jsonl(value, allow_attachment=True)
        if isinstance(header, dict):
            return _redact_capture_jsonl(value, strict_encoding=False)
    # Pretty-printed native JSON (for example Hermes) needs the same decoded
    # string redaction. Plain conversation prose keeps the byte-preserving path.
    if value.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"{"):
        try:
            document = json.loads(value.decode("utf-8-sig"), object_pairs_hook=_capture_object)
        except (ValueError, UnicodeError, RecursionError):
            pass
        else:
            redacted, removed = _redact_capture_value(document, strict_encoding=False)
            if removed:
                bom = b"\xef\xbb\xbf" if value.startswith(b"\xef\xbb\xbf") else b""
                return bom + json.dumps(redacted, ensure_ascii=True).encode("ascii"), removed

    return _PRIVATE_BYTES_RE.subn(PRIVATE_REDACTION.encode("utf-8"), value)


def _capture_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("ambiguous encoded capture record")
        result[key] = item
    return result


def _redact_capture_jsonl(value: bytes, *, allow_attachment: bool = False, strict_encoding: bool = True) -> tuple[bytes, int]:
    lines: list[bytes] = []
    count = 0
    first_record = True
    for line in value.splitlines(keepends=True):
        if not line.strip():
            lines.append(line)
            continue
        try:
            record = json.loads(line.decode("utf-8-sig"), object_pairs_hook=_capture_object)
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("invalid encoded capture record") from None
        if not isinstance(record, dict):
            raise ValueError("unsupported encoded capture record")
        redacted, removed = _redact_capture_value(
            record, allow_attachment=allow_attachment and first_record,
            strict_encoding=strict_encoding,
        )
        first_record = False
        if removed:
            # Serialize decoded strings, rather than replacing across JSON
            # boundaries or leaving escaped copies of private spans behind.
            ending = line[len(line.rstrip(b"\r\n")):]
            bom = b"\xef\xbb\xbf" if line.startswith(b"\xef\xbb\xbf") else b""
            line = bom + json.dumps(
                redacted, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            ).encode("ascii") + ending
        lines.append(line)
        count += removed
    return b"".join(lines), count


def _redact_capture_value(
    value: Any, *, depth: int = 0, allow_attachment: bool = False,
    strict_encoding: bool = True,
) -> tuple[Any, int]:
    if depth > _CAPTURE_JSON_DEPTH:
        raise ValueError("encoded capture nesting exceeds privacy validation limit")
    if isinstance(value, str):
        return redact_private_text(value)
    count = 0
    if isinstance(value, dict):
        if value.get("format") == "cursorDiskKV-v1":
            records = value.get("records")
            if not isinstance(records, list):
                raise ValueError("invalid native cursor capture")
            values = []
            for record in records:
                if (not isinstance(record, list) or len(record) != 2
                        or not isinstance(record[0], str) or not isinstance(record[1], str)):
                    raise ValueError("invalid native cursor capture")
                try:
                    decoded = json.loads(record[1], object_pairs_hook=_capture_object)
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError("invalid native cursor capture") from None
                redacted, removed = _redact_capture_value(decoded, depth=depth + 1, strict_encoding=False)
                values.append([record[0], json.dumps(redacted, ensure_ascii=True) if removed else record[1]])
                count += removed
            value = {**value, "records": values}
        result: dict[str, Any] = {}
        for key, item in value.items():
            redacted_key, removed = redact_private_text(key)
            count += removed
            if redacted_key in result:
                raise ValueError("ambiguous redacted capture record")
            if strict_encoding and key.casefold().startswith("transcript_raw"):
                if not (allow_attachment and key == "transcript_raw_base64"
                        and value.get("format") == _ANTIGRAVITY_EXPORT and isinstance(item, str)):
                    raise ValueError("unsupported encoded capture field")
                try:
                    decoded = base64.b64decode(item, validate=True)
                except (ValueError, binascii.Error):
                    raise ValueError("invalid encoded capture attachment") from None
                redacted, removed = _redact_capture_jsonl(decoded)
                if removed:
                    item = base64.b64encode(redacted).decode("ascii")
            else:
                item, removed = _redact_capture_value(item, depth=depth + 1, strict_encoding=strict_encoding)
            result[redacted_key] = item
            count += removed
        return result, count
    if isinstance(value, list):
        items = []
        for item in value:
            item, removed = _redact_capture_value(item, depth=depth + 1, strict_encoding=strict_encoding)
            items.append(item)
            count += removed
        return items, count
    return value, 0


__all__ = [
    "CaptureDecision",
    "PRIVATE_REDACTION",
    "decide_capture",
    "redact_private_bytes",
    "redact_private_text",
]
