"""Structured output shape for dream-end host-entry consumers.

The dream-end action emits one JSON document on stdout. The wake-start action
emits plaintext wake context and does not use this shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "HostEntryResult",
]

_Status = Literal[
    "skipped",
    "completed",
    "failed",
]

_HINT_TABLE: dict[str, str] = {
    "skipped": "skipped: dream auto gate did not run",
    "completed": "completed: dream maintenance tick completed",
    "failed": "failed: see error payload",
}


@dataclass(frozen=True)
class HostEntryResult:
    """One host-entry result, serializable to the fixed stdout JSON shape."""

    action: str
    status: _Status
    next_step: str
    job_id: str | None
    items_processed: int
    error: dict[str, str] | None  # {"stage": "...", "reason": "..."} or None

    def to_json(self) -> str:
        """Serialize to a single-line JSON string (sorted keys, no newline)."""
        return json.dumps(self.__dict__, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HostEntryResult":
        """Inverse of :meth:`to_json`. Used by tests for round-trip validation."""
        return cls(
            action=payload["action"],
            status=payload["status"],
            next_step=payload["next_step"],
            job_id=payload["job_id"],
            items_processed=payload["items_processed"],
            error=payload["error"],
        )
