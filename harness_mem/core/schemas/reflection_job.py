"""ReflectionJob schema - durable record of one reflection/review unit of work.

v2.4.0 introduces an explicit job lifecycle so that host hooks, schedulers,
or Agent workflows that crash mid-reflection leave behind an inspectable
record (status / phase / lease). This module currently defines the
required-field skeleton; optional fields, ``model_config``, serialization
helpers, and the state machine are added in subsequent slices.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ReflectionJob(BaseModel):
    """Canonical durable record for one reflection/review job."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    project_root: str
    kind: Literal["reflection"] = Field(default="reflection")
    phase: Literal[
        "ingest",
        "prepare",
        "distill",
        "review",
        "metabolism",
        "done",
    ] = Field(default="ingest")
    status: Literal[
        "pending",
        "processing",
        "completed",
        "failed",
        "retryable",
        "needs_distill",
    ] = Field(default="pending")
    source: Literal["user", "agent", "ide_hook", "scheduler"]

    # Optional fields with defaults
    input_refs: list[str] = Field(default_factory=list)
    output_candidate_ids: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None)
    attempt_count: int = Field(default=0)
    lease_owner: str | None = Field(default=None)
    lease_until: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None)

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Datetimes become ISO 8601 strings; lists pass through as JSON arrays
        directly. Mirrors :class:`MetabolismRun.to_dict` so tooling can treat
        all schema blobs uniformly.
        """
        return {
            "id": self.id,
            "project_name": self.project_name,
            "project_root": self.project_root,
            "kind": self.kind,
            "phase": self.phase,
            "status": self.status,
            "source": self.source,
            "input_refs": list(self.input_refs),
            "output_candidate_ids": list(self.output_candidate_ids),
            "error": self.error,
            "attempt_count": self.attempt_count,
            "lease_owner": self.lease_owner,
            "lease_until": self.lease_until.isoformat() if self.lease_until else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReflectionJob":
        """Deserialize from a stored blob.

        Missing optional fields fall back to the schema defaults (Req 1.10).
        Datetime strings are parsed back to aware datetime objects. Pydantic
        handles Literal validation natively, so an out-of-set value for
        ``kind`` / ``phase`` / ``status`` / ``source`` raises ``ValidationError``
        which surfaces the offending field name (Req 1.11).

        We copy the input dict so callers keep their original mapping intact,
        and we only touch fields we recognise — ``model_config={"extra": "allow"}``
        means unknown keys round-trip without us listing them here.
        """
        data = dict(data)
        for field in ("created_at", "updated_at", "lease_until", "completed_at"):
            value = data.get(field)
            if isinstance(value, str):
                data[field] = datetime.fromisoformat(value)
        if "input_refs" not in data or data["input_refs"] is None:
            data["input_refs"] = []
        if "output_candidate_ids" not in data or data["output_candidate_ids"] is None:
            data["output_candidate_ids"] = []
        if "error" not in data:
            data["error"] = None
        if "attempt_count" not in data or data["attempt_count"] is None:
            data["attempt_count"] = 0
        if "lease_owner" not in data:
            data["lease_owner"] = None
        if "lease_until" not in data:
            data["lease_until"] = None
        if "completed_at" not in data:
            data["completed_at"] = None
        if "created_at" not in data:
            data["created_at"] = datetime.now(timezone.utc)
        if "updated_at" not in data:
            data["updated_at"] = datetime.now(timezone.utc)
        return cls(**data)


# State machine -----------------------------------------------------------
#
# Allowed transitions on ``ReflectionJob.status`` (Req 3.1-3.8). Both
# ``completed`` and ``failed`` are terminal and intentionally map to empty
# sets so :func:`validate_transition` rejects every outbound move.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"processing"},
    "processing": {"needs_distill", "completed", "failed", "retryable"},
    "retryable": {"processing"},
    "needs_distill": {"processing", "completed"},
    "completed": set(),
    "failed": set(),
}


def validate_transition(current: str, target: str) -> None:
    """Raise ``ValueError`` if ``current -> target`` is not allowed.

    The error message mentions both the current and the target status so
    callers can surface a useful diagnostic without re-deriving them.
    Terminal states (``completed`` / ``failed``) reject every outbound
    transition because their ``ALLOWED_TRANSITIONS`` entry is an empty set.
    """
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(
            f"unknown ReflectionJob status {current!r}; cannot transition to {target!r}"
        )
    if target not in allowed:
        raise ValueError(
            f"invalid ReflectionJob transition: {current!r} -> {target!r}"
        )


def new_pending_job(
    *,
    project_name: str,
    project_root: str,
    source: Literal["user", "agent", "ide_hook", "scheduler"],
    phase: Literal[
        "ingest", "prepare", "distill", "review", "metabolism", "done"
    ] = "ingest",
    input_refs: list[str] | None = None,
) -> ReflectionJob:
    """Canonical factory for a fresh ReflectionJob (Req 3.11).

    The status field on a freshly created job MUST be ``"pending"`` — the
    state machine assumes that's where the lifecycle starts. Direct
    ``ReflectionJob(...)`` construction is reserved for ``from_dict``
    round-trips where ``status`` may be any persisted value. Business
    code that wants a brand-new job should call this factory.
    """
    return ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        source=source,
        phase=phase,
        status="pending",
        input_refs=list(input_refs) if input_refs else [],
    )
