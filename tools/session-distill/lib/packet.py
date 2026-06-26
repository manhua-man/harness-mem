"""Packet audit and adapter packetization helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def packet_audit_from_jsonl_file(session_path: Path) -> PacketAudit:
    compaction_events = 0
    invalid_json_lines = 0
    orphan_tool_results = 0

    content = session_path.read_text(encoding="utf-8-sig", errors="replace")
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.strip())
        except json.JSONDecodeError:
            invalid_json_lines += 1
            continue

        if record.get("subtype") == "compact_boundary" or record.get("compactMetadata"):
            compaction_events += 1

        content_items = record.get("message", {}).get("content", "")
        if isinstance(content_items, list):
            for item in content_items:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    orphan_tool_results += 1

    return packet_audit_from_counts(
        compaction_events=compaction_events,
        invalid_json_lines=invalid_json_lines,
        orphan_tool_results=orphan_tool_results,
    )


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


def render_session_packet_markdown(
    session: dict[str, Any],
    audit: PacketAudit,
    turns: list[dict[str, Any]],
) -> str:
    """Render the legacy maintenance packet markdown for a parsed session."""

    lines = [
        f"# Session Packet: {session['session_id']} (FULL)",
        "",
        "## Metadata",
        "",
        f"- Source: `{session['file_name']}`",
        f"- Size: {session['size']}",
        f"- Path: `{session['file_path']}`",
        "",
        "## Packet Audit",
        "",
        f"- Coverage: `{audit.coverage}`",
        f"- Compaction events: {audit.compaction_events}",
        f"- Invalid JSON lines skipped: {audit.invalid_json_lines}",
        f"- Orphan tool results: {audit.orphan_tool_results}",
        "",
        "## Distillation Reminder",
        "",
        "- Promote stable workflows, commands, file maps",
        "- Reject noise: token accounting, duplicate context",
        "- One-off context stays in session note",
        "",
    ]

    if not turns:
        lines.extend(["## Content", "", "(No parseable content found in this session)", ""])
    else:
        for i, turn in enumerate(turns, 1):
            lines.extend([f"## Turn {i}", ""])

            if turn.get("user"):
                lines.extend(["### User Request", "", "```text", turn["user"], "```", ""])

            if turn.get("assistant"):
                lines.extend(["### Assistant Response", ""])
                for resp in turn["assistant"][:2]:
                    lines.extend(["```text", resp, "```", ""])

            if turn.get("tools"):
                lines.extend(["### Tools Used", ""])
                for tool in turn["tools"][:5]:
                    lines.append(f"- `{tool['name']}`: {tool['input']}")
                lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Suggested Next Step",
            "",
            "1. Read this packet",
            "2. Query existing memory for dedup",
            "3. Extract candidate drafts from supported evidence",
            "4. Export candidates through harness-mem suggest_* tools",
            "5. Review durable memory through `/hm:review`",
            f"6. Optionally use `/hm:mark {session['session_id']} distilled` for artifact cleanup",
            "",
        ]
    )

    return "\n".join(lines)
