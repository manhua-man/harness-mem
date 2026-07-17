"""Project-scoped transcript admission and private-span redaction.

The capture policy runs before the immutable transcript ledger is written.  A
source excluded here never creates raw revisions, chunks, Observations, jobs,
or derived indexes.  ``<private>...</private>`` spans are replaced before both
the native-byte revision and normalized transcript are hashed.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from harness_mem.config.merge import MergedConfig

PRIVATE_REDACTION = "[private content omitted]"
_PRIVATE_TEXT_RE = re.compile(r"<private\b[^>]*>.*?</private\s*>", re.IGNORECASE | re.DOTALL)
_PRIVATE_BYTES_RE = re.compile(
    rb"<private\b[^>]*>.*?</private\s*>",
    re.IGNORECASE | re.DOTALL,
)


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


def redact_private_text(value: str) -> tuple[str, int]:
    """Remove private spans from normalized transcript text."""

    return _PRIVATE_TEXT_RE.subn(PRIVATE_REDACTION, value)


def redact_private_bytes(value: bytes) -> tuple[bytes, int]:
    """Remove literal private spans without decoding or persisting the secret."""

    return _PRIVATE_BYTES_RE.subn(PRIVATE_REDACTION.encode("utf-8"), value)


__all__ = [
    "CaptureDecision",
    "PRIVATE_REDACTION",
    "decide_capture",
    "redact_private_bytes",
    "redact_private_text",
]
