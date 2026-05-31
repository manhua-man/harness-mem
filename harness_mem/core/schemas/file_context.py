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
        if isinstance(payload.get("cost_hint"), dict):
            payload["cost_hint"] = CostHint.from_dict(payload["cost_hint"])
        if isinstance(payload.get("stale_file_signal"), dict):
            payload["stale_file_signal"] = StaleFileSignal.from_dict(
                payload["stale_file_signal"]
            )
        return cls(**payload)
