"""Structured output shape for host-entry consumers (v2.4.1 Req 5).

The host entry emits exactly one JSON document on stdout per invocation that
reaches the post-argparse stage successfully. :class:`HostEntryResult` is the
in-memory representation of that document; :meth:`HostEntryResult.to_json`
produces the single-line, sorted-key serialization that hook scripts parse with
``jq``.

The ``next_step`` hint always begins with the literal status string followed by
a colon (Req 5.2-5.5, 5.9), so a hook can match ``grep '^needs_distill:'`` after
extracting the field. The one exception is ``skipped_default_off`` where Req 5.8
permits an empty hint (the status alone is unambiguous).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "HostEntryResult",
    "parse_error_payload",
]

_Status = Literal[
    "needs_distill",
    "completed",
    "retryable",
    "failed",
    "skipped_default_off",
]

# Canonical hint table (Req 5.2-5.5, 5.8, 5.9). The first whitespace-delimited
# token of every non-empty hint is exactly ``<status>:`` so hook scripts can
# match on the token without depending on the human-readable tail. The
# ``skipped_default_off`` entry is intentionally empty per Req 5.8.
_HINT_TABLE: dict[str, str] = {
    "needs_distill": "needs_distill: run /hm:distill",
    "completed": "completed: no follow-up needed",
    "retryable": "retryable: re-invoke after backoff",
    "failed": "failed: see error payload",
    "skipped_default_off": "",  # Req 5.8 allows an empty hint
}


def parse_error_payload(error_str: str | None) -> dict[str, str] | None:
    """Parse a v2.4.0 ``ReflectionJob.error`` string into a stage/reason dict.

    v2.4.0 records ``error`` as ``f"{stage}: {reason}"`` (see reflection_jobs
    ``_record_failure``). We split on the first ``": "`` so reasons that contain
    their own colons survive intact.

    - ``"ingest: boom"`` -> ``{"stage": "ingest", "reason": "boom"}``
    - ``"no separator"`` -> ``{"stage": "unknown", "reason": "no separator"}``
    - ``None`` -> ``{"stage": "unknown", "reason": ""}``
    """
    if error_str is None:
        return {"stage": "unknown", "reason": ""}
    stage, sep, reason = error_str.partition(": ")
    if not sep:
        return {"stage": "unknown", "reason": error_str}
    return {"stage": stage, "reason": reason}


@dataclass(frozen=True)
class HostEntryResult:
    """One host-entry result, serializable to the fixed stdout JSON shape."""

    phase: str | None
    status: _Status
    next_step: str
    job_id: str | None
    candidates_written: int
    observations_written: int
    error: dict[str, str] | None  # {"stage": "...", "reason": "..."} or None

    def to_json(self) -> str:
        """Serialize to a single-line JSON string (sorted keys, no newline)."""
        return json.dumps(self.__dict__, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HostEntryResult":
        """Inverse of :meth:`to_json`. Used by tests for round-trip validation."""
        return cls(
            phase=payload["phase"],
            status=payload["status"],
            next_step=payload["next_step"],
            job_id=payload["job_id"],
            candidates_written=payload["candidates_written"],
            observations_written=payload["observations_written"],
            error=payload["error"],
        )

    @classmethod
    def from_reflection_result(cls, result: Any) -> "HostEntryResult":
        """Adapt a v2.4.0 ``ReflectionResult`` to the host-entry output shape.

        - ``phase`` <- ``result.job.phase``
        - ``status`` <- ``result.status``
        - ``next_step`` <- canonical hint for that status
        - ``job_id`` <- ``result.job.id``
        - ``candidates_written`` / ``observations_written`` <- result counts
        - ``error`` <- parsed ``result.job.error`` only when status is
          ``failed`` (Req 5.5); ``None`` otherwise.
        """
        status = result.status
        error = parse_error_payload(result.job.error) if status == "failed" else None
        return cls(
            phase=result.job.phase,
            status=status,
            next_step=_HINT_TABLE[status],
            job_id=result.job.id,
            candidates_written=result.candidates_written,
            observations_written=result.observations_written,
            error=error,
        )

    @classmethod
    def skipped_default_off(cls) -> "HostEntryResult":
        """Canonical default-off skip result (Req 5.8): phase=None, next_step=''."""
        return cls(
            phase=None,
            status="skipped_default_off",
            next_step=_HINT_TABLE["skipped_default_off"],
            job_id=None,
            candidates_written=0,
            observations_written=0,
            error=None,
        )
