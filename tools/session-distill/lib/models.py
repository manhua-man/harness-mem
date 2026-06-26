"""Core data models for the session-distill internal specialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Coverage = Literal["high", "partial"]
CandidateKind = Literal["memory_entry", "rule", "relation_fact", "task_handoff"]
Readiness = Literal[
    "ready-candidate",
    "needs-raw-review",
    "needs-conflict-review",
    "local-only",
    "ephemeral",
]
SuggestToolName = Literal[
    "suggest_memory_entry",
    "suggest_rule",
    "suggest_relation_fact",
    "create_task_handoff",
]


@dataclass(frozen=True)
class SessionSource:
    """A discovered raw session source."""

    session_id: str
    path: Path
    client: str
    project_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionSpan:
    """A selected span inside a raw session."""

    start_turn: int = 0
    end_turn: int | None = None


@dataclass(frozen=True)
class RawSession:
    """Raw content read from a source adapter."""

    source: SessionSource
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PacketAudit:
    """Packet coverage signals that affect promotion readiness."""

    coverage: Coverage = "high"
    compaction_events: int = 0
    invalid_json_lines: int = 0
    orphan_tool_results: int = 0

    @property
    def is_partial(self) -> bool:
        return (
            self.coverage == "partial"
            or self.compaction_events > 0
            or self.invalid_json_lines > 0
            or self.orphan_tool_results > 0
        )


@dataclass(frozen=True)
class KnowledgeEntry:
    """Parsed knowledge-base entry with review classification."""

    section: str
    line_no: int
    text: str
    source_session_id: str | None
    status: str
    reasons: list[str]


@dataclass(frozen=True)
class Packet:
    """Packetized session evidence."""

    session_id: str
    audit: PacketAudit = field(default_factory=PacketAudit)
    project_name: str | None = None
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateDraft:
    """A candidate extracted from packet evidence before harness-mem export."""

    kind: CandidateKind
    content: str
    source_session_id: str
    evidence: tuple[str, ...] = ()
    readiness: Readiness = "ready-candidate"
    category: str | None = None
    source_entity: str | None = None
    target_entity: str | None = None
    relation_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadinessDecision:
    """Boundary decision for export and automatic review."""

    readiness: Readiness
    exportable: bool
    auto_apply_allowed: bool
    requires_manual_review: bool = False
    blocked_reason: str | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class SuggestCall:
    """A planned harness-mem suggestion call.

    This intentionally represents only suggest-like operations. It is not a
    generic MCP call envelope.
    """

    tool_name: SuggestToolName
    arguments: dict[str, Any]
    decision: ReadinessDecision
