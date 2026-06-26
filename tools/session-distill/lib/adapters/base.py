"""Base source adapter protocol and source filtering helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..models import RawSession, SessionSource, SessionSpan


class SourceAdapter(Protocol):
    name: str

    def discover(self, project: str | None = None) -> list[SessionSource]:
        """Return raw session sources for a project or all projects."""

    def read_span(self, source: SessionSource, span: SessionSpan) -> RawSession:
        """Read a bounded span from a source."""

    def build_packet_context(self, source: SessionSource) -> dict[str, object]:
        """Return adapter metadata used by the packetizer."""


def source_is_self_session(
    source: SessionSource,
    *,
    current_session_id: str | None = None,
) -> bool:
    """Return whether *source* is the active distillation session itself."""

    if current_session_id and source.session_id == current_session_id:
        return True

    metadata = source.metadata
    if metadata.get("session_distill_self") is True:
        return True
    if metadata.get("is_self_session") is True:
        return True
    return metadata.get("origin") == "session-distill"


def exclude_self_sessions(
    sources: Iterable[SessionSource],
    *,
    current_session_id: str | None = None,
) -> list[SessionSource]:
    """Drop active self-session sources before packetization or export."""

    return [
        source
        for source in sources
        if not source_is_self_session(source, current_session_id=current_session_id)
    ]
