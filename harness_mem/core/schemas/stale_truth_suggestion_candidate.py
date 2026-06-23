"""StaleTruthSuggestionCandidate — pending proposal to mark a truth stale.

v2.3.1 metabolism pass creates these for confirmed truths that have not
been surfaced (no ``wake_surfaced`` and no ``search_hit``) in the last
``silence_days`` (default 60). Confirming the candidate sets
``valid_to = now`` on the target — it does NOT delete or replace the
record. The truth remains queryable via ``include_history=True``.

Contract:

* ``last_surfaced_at`` data source: the **newer** of the v2.2 field
  (``last_accessed_at`` / ``last_surfaced_at`` on the truth) and the
  v2.3.0 ``RetrievalSignal`` table's most recent ``wake_surfaced`` /
  ``search_hit`` for that target. ``None`` only when neither source has
  any surface event.
* ``days_since_last_surface``: derived from ``last_surfaced_at`` if
  set, else from the truth's ``created_at``. Always non-negative.
* Scope: ``target_kind`` accepts ``"relation_fact"`` for forward
  compatibility, but the v2.3.1 algorithm in ``_propose_stale`` only
  processes ``memory_entry`` and ``confirmed_rule``. Fact stale
  detection is deferred until ``RelationFact`` carries enough surface
  signal to be reliable.
"""

from datetime import datetime, timezone
from typing import Any
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class StaleTruthSuggestionCandidate(BaseModel):
    """Pending request to mark a long-silent confirmed truth historical.

    The metabolism pass populates ``last_surfaced_at`` and
    ``days_since_last_surface`` from the proposer's view of the truth
    plus the v2.3.0 ``RetrievalSignal`` aggregate. The schema does not
    enforce a relationship between the two: when ``last_surfaced_at``
    is ``None``, the proposer is responsible for computing
    ``days_since_last_surface`` from the underlying truth's
    ``created_at``. ``days_since_last_surface`` is required and
    non-negative.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    target_id: str
    target_kind: Literal["memory_entry", "confirmed_rule", "relation_fact"]
    last_surfaced_at: datetime | None = None
    days_since_last_surface: int = Field(..., ge=0)
    evidence_signal_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "accepted", "rejected"] = "pending"
    metabolism_run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "id": self.id,
            "project_name": self.project_name,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "last_surfaced_at": (
                self.last_surfaced_at.isoformat() if self.last_surfaced_at else None
            ),
            "days_since_last_surface": self.days_since_last_surface,
            "evidence_signal_ids": list(self.evidence_signal_ids),
            "status": self.status,
            "metabolism_run_id": self.metabolism_run_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        for key, value in (self.model_extra or {}).items():
            if key not in data:
                data[key] = value.isoformat() if isinstance(value, datetime) else value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "StaleTruthSuggestionCandidate":
        data = dict(data)  # don't mutate caller's dict
        if isinstance(data.get("last_surfaced_at"), str):
            data["last_surfaced_at"] = datetime.fromisoformat(data["last_surfaced_at"])
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "evidence_signal_ids" not in data:
            data["evidence_signal_ids"] = []
        if "status" not in data:
            data["status"] = "pending"
        return cls(**data)
