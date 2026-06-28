"""MetabolismRun schema - internal append-only maintenance scan record."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class MetabolismRun(BaseModel):
    """Append-only record of one internal scan used by dream maintenance.

    Standalone MCP scan tools were removed; dream remains the product-facing
    maintenance loop. This schema is retained for internal audit compatibility
    while dream owns scheduling, ledger, and undo.

    ``notes`` is modeled as a list of strings (rather than a single
    human-readable string) so the replay-window selector can append
    ``truncated_within_<dim>`` annotations without string concatenation
    gymnastics; one note per dimension reads cleanly in tooling.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    kind: Literal["preview", "metabolism"] = Field(default="preview")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None)
    status: Literal["preview", "completed", "error"] = Field(default="preview")
    input_window: dict = Field(default_factory=dict)
    selected_signal_ids: list[str] = Field(default_factory=list)
    output_counts: dict[str, int] = Field(
        default_factory=lambda: {"suggestions": 0},
        description="Counters extendable by future slices without migration.",
    )
    duration_ms: int = Field(default=0)
    notes: list[str] | None = Field(
        default=None,
        description="Optional annotations (e.g. truncated_within_observations).",
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "kind": self.kind,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "input_window": self.input_window,
            "selected_signal_ids": self.selected_signal_ids,
            "output_counts": self.output_counts,
            "duration_ms": self.duration_ms,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetabolismRun":
        for field in ("started_at", "completed_at"):
            value = data.get(field)
            if isinstance(value, str):
                data[field] = datetime.fromisoformat(value)
        if "kind" not in data:
            data["kind"] = "preview"
        if "status" not in data:
            data["status"] = "preview"
        if "input_window" not in data:
            data["input_window"] = {}
        if "selected_signal_ids" not in data:
            data["selected_signal_ids"] = []
        if "output_counts" not in data:
            data["output_counts"] = {"suggestions": 0}
        if "duration_ms" not in data:
            data["duration_ms"] = 0
        if "notes" not in data:
            data["notes"] = None
        if "completed_at" not in data:
            data["completed_at"] = None
        return cls(**data)
