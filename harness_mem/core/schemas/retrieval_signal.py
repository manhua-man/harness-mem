"""RetrievalSignal schema - observable event in the retrieval / review loop."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

# Initial whitelist of well-known signal types. Callers may use this for
# validation, but the schema itself stays open (``signal_type: str``) so
# future slices can introduce new types without a migration.
VALID_SIGNAL_TYPES: frozenset[str] = frozenset(
    {
        "confirmed",
        "rejected",
        "wake_surfaced",
        "search_hit",
        "context_outcome",
        "skill_result_success",
        "skill_result_failure",
        "supersede_completed",
    }
)

# Initial whitelist of well-known target kinds. Same forward-compat note.
VALID_TARGET_KINDS: frozenset[str] = frozenset(
    {
        "memory_entry",
        "rule",
        "skill",
        "candidate",
        "observation",
        "supersede",
        "context_source",
    }
)


class RetrievalSignal(BaseModel):
    """A single observable event about how memory was used.

    The signal itself is not truth; it's evidence that the replay-window
    selector consumes when picking the next metabolism input window.

    ``signal_type`` and ``target_kind`` are kept as plain ``str`` (not
    ``Literal``) because the design lists them as extendable whitelists.
    Callers that want strict validation can compare against
    :data:`VALID_SIGNAL_TYPES` / :data:`VALID_TARGET_KINDS`.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    signal_type: str
    target_kind: str
    target_id: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    value: float | None = Field(default=None)
    context: dict | None = Field(default=None)

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "signal_type": self.signal_type,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "recorded_at": self.recorded_at.isoformat(),
            "value": self.value,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RetrievalSignal":
        if isinstance(data.get("recorded_at"), str):
            data["recorded_at"] = datetime.fromisoformat(data["recorded_at"])
        if "value" not in data:
            data["value"] = None
        if "context" not in data:
            data["context"] = None
        return cls(**data)
