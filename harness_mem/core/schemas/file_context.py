"""File-context schema — read-only, source-attributed file memory lookup.

v2.5.2 introduces an explicit ``file_context(path)`` helper/tool that lets an
agent ask "what does memory already know about this file?" before opening the
file itself. The result is pure data: compact items, drilldown pointers, a
cost hint, and an explicit stale-file signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from harness_mem.core.schemas.context_assembly_plan import DrilldownPointer


FileContextTruthStatus = Literal[
    "confirmed_current",
    "historical",
    "reference",
    "uncertain",
]
FileContextItemKind = Literal[
    "project_profile_key_file",
    "code_fingerprint",
    "code_symbol",
    "module_dependency",
    "observation",
    "memory_entry",
    "confirmed_rule",
    "task_handoff",
    "skill_hint",
]
StaleFileSignalState = Literal[
    "none",
    "possibly_stale",
    "historical_path_match",
    "newer_activity_exists",
]


class FileContextItem(BaseModel):
    """One compact, source-attributed item in a file-context result."""

    kind: FileContextItemKind
    source_ids: list[str] = Field(min_length=1)
    why_included: str = Field(min_length=1)
    summary: str = ""
    truth_status: FileContextTruthStatus = "reference"
    drilldown: DrilldownPointer | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source_ids": list(self.source_ids),
            "why_included": self.why_included,
            "summary": self.summary,
            "truth_status": self.truth_status,
            "drilldown": self.drilldown.to_dict() if self.drilldown else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileContextItem":
        payload = dict(data)
        drilldown = payload.get("drilldown")
        if isinstance(drilldown, dict):
            payload["drilldown"] = DrilldownPointer.from_dict(drilldown)
        return cls(**payload)


class FileFingerprint(BaseModel):
    """Current local file identity used by v4.3 code-memory federation."""

    source_id: str
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    modified_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileFingerprint":
        payload = dict(data)
        if isinstance(payload.get("modified_at"), str):
            payload["modified_at"] = datetime.fromisoformat(payload["modified_at"])
        return cls(**payload)


CodeSymbolKind = Literal["class", "function", "async_function", "import"]


class CodeSymbol(BaseModel):
    """A lightweight current-code symbol or dependency reference."""

    source_id: str
    name: str
    kind: CodeSymbolKind
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "kind": self.kind,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeSymbol":
        return cls(**data)


CodeEvidenceStaleStatus = Literal[
    "current",
    "stale",
    "missing_reference",
    "missing_current_file",
    "unknown",
]
CodeEvidenceLineRangeStatus = Literal[
    "not_applicable",
    "valid",
    "missing",
    "out_of_bounds",
]


class CodeEvidence(BaseModel):
    """Source-attributed current-code evidence for memory references."""

    source_id: str
    path: str
    fingerprint: str | None = None
    line_range: tuple[int, int] | None = None
    symbol: str | None = None
    kind: str = "file"
    stale_status: CodeEvidenceStaleStatus = "current"
    stale_reason: str = ""
    referenced_fingerprint: str | None = None
    current_fingerprint: str | None = None
    line_range_status: CodeEvidenceLineRangeStatus = "not_applicable"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "path": self.path,
            "fingerprint": self.fingerprint,
            "line_range": list(self.line_range) if self.line_range else None,
            "symbol": self.symbol,
            "kind": self.kind,
            "stale_status": self.stale_status,
            "stale_reason": self.stale_reason,
            "referenced_fingerprint": self.referenced_fingerprint,
            "current_fingerprint": self.current_fingerprint,
            "line_range_status": self.line_range_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeEvidence":
        payload = dict(data)
        line_range = payload.get("line_range")
        if isinstance(line_range, list):
            payload["line_range"] = tuple(line_range)
        return cls(**payload)


class CostHint(BaseModel):
    """Approximate expansion cost for the returned drilldown targets."""

    estimated_tokens: int = Field(ge=0)
    disclosure_level: str

    def to_dict(self) -> dict:
        return {
            "estimated_tokens": self.estimated_tokens,
            "disclosure_level": self.disclosure_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CostHint":
        return cls(**data)


class StaleFileSignal(BaseModel):
    """Explicit stale-file state; always present, never omitted."""

    state: StaleFileSignalState
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StaleFileSignal":
        return cls(**data)


class FileContextResult(BaseModel):
    """Serializable result payload for the ``file_context(path)`` helper."""

    project_name: str | None = None
    path: str = ""
    normalized_path: str = ""
    path_provided: bool = True
    notice: str = ""
    items: list[FileContextItem] = Field(default_factory=list)
    file_fingerprint: FileFingerprint | None = None
    code_symbols: list[CodeSymbol] = Field(default_factory=list)
    code_evidence: list[CodeEvidence] = Field(default_factory=list)
    cost_hint: CostHint
    stale_file_signal: StaleFileSignal
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "path": self.path,
            "normalized_path": self.normalized_path,
            "path_provided": self.path_provided,
            "notice": self.notice,
            "items": [item.to_dict() for item in self.items],
            "item_count": len(self.items),
            "file_fingerprint": (
                self.file_fingerprint.to_dict() if self.file_fingerprint else None
            ),
            "code_symbols": [symbol.to_dict() for symbol in self.code_symbols],
            "code_evidence": [evidence.to_dict() for evidence in self.code_evidence],
            "cost_hint": self.cost_hint.to_dict(),
            "stale_file_signal": self.stale_file_signal.to_dict(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileContextResult":
        payload = dict(data)
        if isinstance(payload.get("created_at"), str):
            payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["items"] = [
            FileContextItem.from_dict(item) if isinstance(item, dict) else item
            for item in payload.get("items", [])
        ]
        if isinstance(payload.get("file_fingerprint"), dict):
            payload["file_fingerprint"] = FileFingerprint.from_dict(
                payload["file_fingerprint"]
            )
        payload["code_symbols"] = [
            CodeSymbol.from_dict(item) if isinstance(item, dict) else item
            for item in payload.get("code_symbols", [])
        ]
        payload["code_evidence"] = [
            CodeEvidence.from_dict(item) if isinstance(item, dict) else item
            for item in payload.get("code_evidence", [])
        ]
        if isinstance(payload.get("cost_hint"), dict):
            payload["cost_hint"] = CostHint.from_dict(payload["cost_hint"])
        if isinstance(payload.get("stale_file_signal"), dict):
            payload["stale_file_signal"] = StaleFileSignal.from_dict(
                payload["stale_file_signal"]
            )
        return cls(**payload)
