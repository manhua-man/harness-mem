"""Packet audit and adapter packetization helpers."""

from __future__ import annotations

from .adapters.base import SourceAdapter, source_is_self_session
from .models import Packet, PacketAudit, RawSession, SessionSource, SessionSpan


def packet_audit_from_counts(
    *,
    compaction_events: int = 0,
    invalid_json_lines: int = 0,
    orphan_tool_results: int = 0,
) -> PacketAudit:
    coverage = (
        "partial"
        if compaction_events or invalid_json_lines or orphan_tool_results
        else "high"
    )
    return PacketAudit(
        coverage=coverage,
        compaction_events=compaction_events,
        invalid_json_lines=invalid_json_lines,
        orphan_tool_results=orphan_tool_results,
    )


def raw_review_required(audit: PacketAudit) -> bool:
    return audit.is_partial


def packet_audit_from_raw_session(raw_session: RawSession) -> PacketAudit:
    return packet_audit_from_counts(
        compaction_events=int(raw_session.metadata.get("compaction_events", 0) or 0),
        invalid_json_lines=int(raw_session.metadata.get("invalid_json_lines", 0) or 0),
        orphan_tool_results=int(raw_session.metadata.get("orphan_tool_results", 0) or 0),
    )


def packet_from_source(
    adapter: SourceAdapter,
    source: SessionSource,
    *,
    span: SessionSpan | None = None,
    current_session_id: str | None = None,
) -> Packet | None:
    """Build a packet through the SourceAdapter interface.

    Returning ``None`` for a self-session keeps active distillation sessions out
    of candidate promotion paths.
    """

    if source_is_self_session(source, current_session_id=current_session_id):
        return None

    raw_session = adapter.read_span(source, span or SessionSpan())
    packet_context = adapter.build_packet_context(source)
    metadata = {
        **packet_context,
        **raw_session.metadata,
    }
    return Packet(
        session_id=source.session_id,
        project_name=source.project_name,
        text=raw_session.text,
        audit=packet_audit_from_raw_session(raw_session),
        metadata=metadata,
    )
