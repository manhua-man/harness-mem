"""DreamRun / DreamItem schemas for v3.1 auto dream maintenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


DreamFinalAction = Literal["applied", "rejected", "archived", "failed"]
DreamProposedAction = Literal[
    "merge",
    "mark_stale",
    "supersede",
    "reject_uncertain",
    "archive_unclassifiable",
]
DreamRisk = Literal["low", "medium", "high"]
DreamStatus = Literal["processing", "completed", "failed"]


class DreamItem(BaseModel):
    """One parsed and handled item inside a DreamRun.

    Every Dream item reaches a terminal result in the same run. Manual Review
    remains available for audit and undo, but Dream does not create an
    automatic pending-review queue.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_kind: str
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    risk: DreamRisk = "medium"
    proposed_action: DreamProposedAction
    final_action: DreamFinalAction
    reason: str
    undo: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    model_config = {"extra": "allow"}

    @field_validator("source_kind", "source_id", "reason")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "evidence_ids": list(self.evidence_ids),
            "risk": self.risk,
            "proposed_action": self.proposed_action,
            "final_action": self.final_action,
            "reason": self.reason,
            "undo": self.undo,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DreamItem":
        data = dict(data)
        if "evidence_ids" not in data or data["evidence_ids"] is None:
            data["evidence_ids"] = []
        if "undo" not in data or data["undo"] is None:
            data["undo"] = {}
        if "result" not in data or data["result"] is None:
            data["result"] = {}
        if "error" not in data:
            data["error"] = None
        # Historical ledgers remain readable after the intermediate state was
        # removed. They are projected as closed audit records, not re-opened.
        if data.get("final_action") == "pending_review":
            data["final_action"] = "archived"
        return cls(**data)


class DreamRun(BaseModel):
    """Append-only ledger record for one auto dream maintenance run."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: DreamStatus = "completed"
    trigger_source: Literal["user", "agent", "ide_hook", "scheduler"] = "agent"
    reflection_job_id: str | None = None
    policy_version: str = "v3.1"
    input_window: dict[str, Any] = Field(default_factory=dict)
    selected_signal_ids: list[str] = Field(default_factory=list)
    items: list[DreamItem] = Field(default_factory=list)
    handling_summary: dict[str, int] = Field(
        default_factory=lambda: {
            "processed": 0,
            "applied": 0,
            "rejected": 0,
            "archived": 0,
            "failed": 0,
        }
    )
    duration_ms: int = 0
    notes: list[str] | None = None

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: object) -> None:
        self.handling_summary = _summary_for_items(self.items, self.handling_summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "trigger_source": self.trigger_source,
            "reflection_job_id": self.reflection_job_id,
            "policy_version": self.policy_version,
            "input_window": self.input_window,
            "selected_signal_ids": list(self.selected_signal_ids),
            "items": [item.to_dict() for item in self.items],
            "handling_summary": dict(self.handling_summary),
            "duration_ms": self.duration_ms,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DreamRun":
        data = dict(data)
        for field in ("started_at", "completed_at"):
            value = data.get(field)
            if isinstance(value, str) and value:
                data[field] = datetime.fromisoformat(value)
        if "items" not in data or data["items"] is None:
            data["items"] = []
        data["items"] = [
            item if isinstance(item, DreamItem) else DreamItem.from_dict(item)
            for item in data["items"]
        ]
        if "handling_summary" not in data or data["handling_summary"] is None:
            data["handling_summary"] = {}
        if "selected_signal_ids" not in data or data["selected_signal_ids"] is None:
            data["selected_signal_ids"] = []
        if "notes" not in data:
            data["notes"] = None
        if "reflection_job_id" not in data:
            data["reflection_job_id"] = None
        return cls(**data)


def _summary_for_items(
    items: list[DreamItem],
    existing: dict[str, int] | None = None,
) -> dict[str, int]:
    summary = {
        "processed": len(items),
        "applied": 0,
        "rejected": 0,
        "archived": 0,
        "failed": 0,
    }
    for item in items:
        summary[item.final_action] += 1
    if existing:
        for key, value in existing.items():
            if key not in summary and key != "pending_review":
                summary[key] = int(value)
    return summary
