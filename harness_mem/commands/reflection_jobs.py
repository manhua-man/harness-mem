"""reflection_jobs command module — idempotency, lease, and reflection_once.

This module hosts the helpers used by the business command
:func:`reflection_once`:

* :func:`compute_idempotency_key` — deterministic key for duplicate
  trigger detection.
* :func:`acquire_lease` — compare-and-set lease acquisition with
  expired-lease recovery and a max-retry kill switch.
* :func:`reflection_once` — the v2.4.0 business-command entry point
  used by MCP handlers and host hooks alike.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from harness_mem.commands.support import find_project_root
from harness_mem.core.schemas.reflection_job import ReflectionJob, validate_transition
from harness_mem.storage.reflection_job_store import ReflectionJobStore


def compute_idempotency_key(
    project_name: str,
    source: str,
    phase: str,
    session_ids: Iterable[str],
    trigger_id: str | None,
) -> str:
    """Return a deterministic idempotency key for a reflection job.

    The hash is stable across process restarts because:

    - ``session_ids`` are sorted lexicographically before being joined,
      so caller-supplied ordering doesn't change the digest.
    - ``trigger_id`` of ``None`` is normalised to the empty string so
      callers without an explicit trigger get a single canonical key.
    - We use ``"|"`` as a separator and don't collide with valid
      session ids; UUIDs and slug-style ids never contain pipes.

    The 32-hex truncation is plenty for collision avoidance at our scale
    (we'd need ~2^64 jobs to hit the birthday bound) and keeps the
    column compact for SQLite indexing.
    """
    parts = [
        project_name,
        source,
        phase,
        ",".join(sorted(session_ids)),
        trigger_id or "",
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


__all__ = [
    "compute_idempotency_key",
    "acquire_lease",
    "reflection_once",
    "ReflectionResult",
    "RetryableError",
]


# ---- lease acquisition ---------------------------------------------------
#
# ``acquire_lease`` is the single chokepoint where a worker proves it
# owns a job. It encapsulates three rules that the design doc spreads
# across Req 4 + P3/P7/P8:
#
# 1. Eligibility — only ``pending`` / ``retryable`` (no owner) and
#    ``processing`` with an EXPIRED lease are up for grabs. Live leases
#    are off-limits regardless of who's asking.
# 2. Atomicity — every state mutation goes through
#    ``ReflectionJobStore.compare_and_set`` so concurrent acquirers
#    can't both win. A failed CAS returns ``False``, never raises.
# 3. Bounded retries — once ``attempt_count >= max_retries`` the job
#    is flipped to ``failed`` and stays there. Subsequent calls return
#    ``False`` idempotently.


async def acquire_lease(
    job_store: ReflectionJobStore,
    job_id: str,
    owner: str,
    duration_seconds: int = 300,
    max_retries: int = 5,
) -> bool:
    """Compare-and-set lease acquisition with expiry recovery (Req 4).

    Returns ``True`` iff this caller now owns the lease. ``False`` covers
    every other outcome — unknown job, ineligible status, live lease held
    by someone else, lost CAS race, or ``attempt_count`` already at the
    retry ceiling. The function never raises; failed acquisition is a
    routine outcome (Req 4.7).

    Args:
        job_store: Persistence layer used for the read + CAS.
        job_id: Job to acquire.
        owner: Identifier stamped onto ``lease_owner`` (typically
            ``f"{hostname}:{pid}"`` or a worker name).
        duration_seconds: How long the new lease lasts. ``lease_until``
            is set to ``now + duration_seconds`` (Req 4.4).
        max_retries: Hard ceiling on ``attempt_count``. Default 5 mirrors
            the design's "5 acquisitions, then fail" rule (Req 4.8).

    Acquisition increments ``attempt_count`` on EVERY successful claim,
    including the very first one. So a job that's processed once cleanly
    finishes with ``attempt_count == 1``; a job that's retried once ends
    at ``attempt_count == 2``. This pairs cleanly with Req 4.8: when
    ``attempt_count`` reaches ``max_retries``, the job is force-failed
    rather than re-acquired.
    """
    job = job_store.get(job_id)
    if job is None:
        # Unknown job — caller raced a delete or supplied a bogus id.
        return False

    # ---- max-retry kill switch (Req 4.8) --------------------------------
    # If the job has already burned through its retry budget, mark it
    # failed (idempotently) and refuse the lease. We use a CAS guard so
    # we don't stomp a row another worker is concurrently transitioning;
    # if the CAS misses for any reason, we just return False — the job
    # is either already failed or someone else is handling it.
    if job.attempt_count >= max_retries:
        if job.status != "failed":
            job_store.compare_and_set(
                job_id=job_id,
                expected_status=job.status,
                expected_lease_owner=job.lease_owner,
                updates={
                    "status": "failed",
                    "error": "max_retries_exceeded",
                    "lease_owner": None,
                    "lease_until": None,
                },
            )
        return False

    # ---- eligibility check (Req 4.1, 4.2) -------------------------------
    now = datetime.now(timezone.utc)
    eligible = False
    if job.status in ("pending", "retryable") and job.lease_owner is None:
        eligible = True
    elif (
        job.status == "processing"
        and job.lease_until is not None
        and job.lease_until < now
    ):
        # Expired lease — the previous owner crashed or stalled. Anyone
        # may re-acquire. Note: we deliberately do NOT call
        # validate_transition here. ``processing -> processing`` is not
        # a state-machine transition, it's a re-acquisition of the same
        # logical state under a new owner.
        eligible = True

    if not eligible:
        return False

    # ---- acquire (Req 4.3, 4.4, 4.5) ------------------------------------
    lease_until = now + timedelta(seconds=duration_seconds)
    return job_store.compare_and_set(
        job_id=job_id,
        expected_status=job.status,
        expected_lease_owner=job.lease_owner,
        updates={
            "status": "processing",
            "lease_owner": owner,
            "lease_until": lease_until,
            "attempt_count": job.attempt_count + 1,
        },
    )


# ---- reflection_once -----------------------------------------------------
#
# v2.4.0 reflection trigger entry point. Wraps idempotency, job creation,
# and lease acquisition behind a single async call so MCP handlers and
# host hooks share identical behavior (Req 6.1). The actual ingest +
# prepare + distill execution pipeline lands in a later slice — this
# slice ships the orchestrating shell and the defer_to_agent shortcut
# that the v2.4.0 default config takes.


class RetryableError(Exception):
    """Marker for errors that should leave the job in ``retryable`` (Req 6.3).

    Defined here so future pipeline phases can raise it explicitly. Not
    raised by the v2.4.0 shell itself — the shell only classifies
    exceptions caught from would-be pipeline calls.
    """


@dataclass
class ReflectionResult:
    """Result of a :func:`reflection_once` invocation.

    ``status`` is the caller-facing terminal classification — for an
    in-flight job we surface as ``retryable`` so the caller knows to
    poll/wait rather than treat the call as final. ``created`` lets the
    caller distinguish "I just kicked off this job" from "this job was
    already there", which matters for telemetry but not for correctness
    (the candidate-side effects are identical either way per Req 5.2).
    """

    job: ReflectionJob
    status: Literal["needs_distill", "completed", "retryable", "failed"]
    candidates_written: int
    observations_written: int
    created: bool


# Statuses that map to "still in flight from the caller's perspective".
# We surface them as ``retryable`` from reflection_once so callers do
# not branch on internal lifecycle states.
_IN_FLIGHT_STATUSES = frozenset({"pending", "processing"})

# Statuses that already represent a terminal-from-caller outcome.
_CALLER_TERMINAL_STATUSES = frozenset(
    {"needs_distill", "completed", "retryable", "failed"}
)


def _coerce_caller_status(
    status: str,
) -> Literal["needs_distill", "completed", "retryable", "failed"]:
    """Project an internal job status onto the caller-facing 4-value set.

    Internal statuses ``pending`` / ``processing`` mean the job is still
    in flight; from the caller's perspective that's indistinguishable
    from ``retryable`` (poll / wait). All other statuses already match
    the caller-facing set and pass through unchanged.
    """
    if status in _IN_FLIGHT_STATUSES:
        return "retryable"
    if status in _CALLER_TERMINAL_STATUSES:
        return status  # type: ignore[return-value]
    # Unknown status — treat as retryable so the caller doesn't get
    # locked out, but don't silently corrupt the model.
    return "retryable"


def _synthetic_failure(
    *,
    project_name: str,
    project_root: str,
    source: Literal["user", "agent", "ide_hook", "scheduler"],
    error: str,
) -> ReflectionResult:
    """Build a non-persisted failure result without touching the store.

    Used when the job_store itself is unusable (Req 10.5, 10.7) — we
    must never raise out of reflection_once, so we return a synthetic
    ReflectionJob carrying the error and let the caller decide what
    to do.
    """
    job = ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        source=source,
        status="failed",
        error=error,
    )
    return ReflectionResult(
        job=job,
        status="failed",
        candidates_written=0,
        observations_written=0,
        created=False,
    )


async def reflection_once(
    project_name: str,
    config: dict[str, Any],
    *,
    source: Literal["user", "agent", "ide_hook", "scheduler"] = "agent",
    session_ids: list[str] | None = None,
    trigger_id: str | None = None,
    project_root: str | None = None,
    job_store: ReflectionJobStore | None = None,
) -> ReflectionResult:
    """v2.4.0 reflection trigger entry point (Req 5, 6, 9, 10).

    Behavior contract — implemented in this order:

    1. Resolve project (Req 5.4) — if ``project_root`` is None, first
       try the commands-layer project-root resolver for ``project_name``;
       if that finds nothing, fall back to the current working
       directory.
    2. Compute idempotency key (Req 5.1) — covers project / source /
       phase / sorted session_ids / trigger_id.
    3. Job-store guard (Req 10.5, 10.7) — a missing store yields a
       synthetic failure result; we never raise.
    4. Idempotency lookup (Req 5.2) — non-terminal match short-circuits
       and returns ``created=False``.
    5. Terminal+same-trigger guard (Req 5.3) — if a finished job with
       the same key + same trigger_id exists, return it; otherwise
       proceed to step 6.
    6. Create new job — built from the resolved inputs and saved.
    7. Defer-to-agent shortcut (Req 6.2) — when the config asks for it,
       transition pending → processing → needs_distill in two CAS calls
       under the 500ms budget without acquiring a lease.
    8. Lease + execution (Req 6.3-6.5, 9.x) — v2.4.0 default behavior
       falls back to defer_to_agent when no pipeline is wired.
    9. Candidate tracking (Req 9.3, 9.4) — the v2.4.0 default path
       writes zero candidates / observations; the result reflects that.
    10. Error handling (Req 6.3, 6.4, 10.5) — all exceptions are caught,
        classified, and returned as failure / retryable results.
    """
    # ---- 1. Resolve project (Req 5.4) -----------------------------------
    if project_root is None:
        resolved_root = find_project_root(project_name)
        project_root = str(resolved_root) if resolved_root is not None else str(Path.cwd())

    session_id_list = list(session_ids) if session_ids else []

    # ---- 2. Compute idempotency key (Req 5.1) ---------------------------
    # phase is "ingest" for the entry point — that's the lifecycle's
    # initial phase per the schema default. The key is stable across
    # process restarts so duplicate triggers collapse to the same row.
    phase: Literal["ingest", "prepare", "distill", "review", "metabolism", "done"] = (
        "ingest"
    )
    key = compute_idempotency_key(
        project_name=project_name,
        source=source,
        phase=phase,
        session_ids=session_id_list,
        trigger_id=trigger_id,
    )

    # ---- 3. Job-store availability guard (Req 10.5, 10.7) ---------------
    if job_store is None:
        return _synthetic_failure(
            project_name=project_name,
            project_root=project_root,
            source=source,
            error="job_store_unavailable",
        )

    # ---- 4. Idempotency lookup (Req 5.2) --------------------------------
    # find_by_idempotency_key only returns non-terminal rows, so an
    # in-flight job collapses cleanly here without us needing to filter.
    # Lookup failures (locked DB, corrupt index) must NOT escape per
    # Req 10.5 — degrade to a synthetic failure result instead.
    try:
        existing = job_store.find_by_idempotency_key(key)
    except Exception as exc:
        return _synthetic_failure(
            project_name=project_name,
            project_root=project_root,
            source=source,
            error=f"idempotency_lookup: {exc}",
        )
    if existing is not None:
        # In-flight (pending / processing) maps to retryable from the
        # caller's perspective — Req 5.2 says we just return the
        # existing job, and the caller decides what to do based on
        # status. needs_distill / retryable / failed pass through.
        return ReflectionResult(
            job=existing,
            status=_coerce_caller_status(existing.status),
            candidates_written=0,
            observations_written=0,
            created=False,
        )

    # ---- 5. Terminal+different-trigger guard (Req 5.3) ------------------
    # Convention: input_refs[0] holds trigger_id when present, for
    # Req 5.3 disambiguation. Future schema change should promote
    # trigger_id to a typed column. Lookup failures degrade to
    # synthetic failure (Req 10.5).
    try:
        terminal = job_store.find_terminal_by_idempotency_key(key)
    except Exception as exc:
        return _synthetic_failure(
            project_name=project_name,
            project_root=project_root,
            source=source,
            error=f"idempotency_lookup_terminal: {exc}",
        )
    if terminal is not None:
        existing_trigger = (
            terminal.input_refs[0] if terminal.input_refs else None
        )
        if (existing_trigger or None) == (trigger_id or None):
            # Same trigger replayed after a terminal job — return that
            # job (Req 5.3) instead of creating a duplicate.
            return ReflectionResult(
                job=terminal,
                status=_coerce_caller_status(terminal.status),
                candidates_written=0,
                observations_written=0,
                created=False,
            )
        # Different trigger reusing the same parameters — fall through
        # and create a new job (Req 5.3).

    # ---- 6. Create new job ----------------------------------------------
    # extra="allow" lets us stash idempotency_key on model_extra so the
    # store's _row_from_job picks it up for the index column. We build
    # an Any-typed kwargs dict because Pydantic accepts unknown fields
    # under ``extra="allow"`` but mypy can't see them on the typed
    # ReflectionJob signature.
    input_refs: list[str] = [trigger_id] if trigger_id else []
    extra_kwargs: dict[str, Any] = {"idempotency_key": key}
    job = ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        source=source,
        status="pending",
        phase=phase,
        attempt_count=0,
        input_refs=input_refs,
        **extra_kwargs,
    )
    try:
        job_store.save(job)
    except Exception as exc:  # store unavailable mid-flight — Req 10.5
        return _synthetic_failure(
            project_name=project_name,
            project_root=project_root,
            source=source,
            error=f"save: {exc}",
        )

    # ---- 7. Defer-to-agent shortcut (Req 6.2) ---------------------------
    # Default behavior in v2.4.0 is defer_to_agent — actual
    # ingest/prepare/distill pipeline is wired in a later slice. Until
    # then, any non-explicit config produces a needs_distill outcome.
    distill_mode = (config.get("distill") or {}).get("mode", "defer_to_agent")
    if distill_mode == "defer_to_agent":
        # defer_to_agent bypasses the lease because no LLM call is made
        # — we transition pending → processing → needs_distill directly
        # via two CAS calls. The state machine forbids
        # pending → needs_distill in one hop, so we stage through
        # processing per Req 3.1 + 3.3.
        try:
            now = datetime.now(timezone.utc)
            owner = f"reflection_once:defer:{os.getpid()}"
            validate_transition("pending", "processing")
            ok1 = job_store.compare_and_set(
                job_id=job.id,
                expected_status="pending",
                expected_lease_owner=None,
                updates={
                    "status": "processing",
                    "lease_owner": owner,
                    "lease_until": now + timedelta(seconds=60),
                },
            )
            if not ok1:
                # Someone else (or our own retry) raced us — re-read and
                # return whatever shape exists. This still satisfies
                # Req 6.2 because we don't block.
                refreshed = job_store.get(job.id) or job
                return ReflectionResult(
                    job=refreshed,
                    status=_coerce_caller_status(refreshed.status),
                    candidates_written=0,
                    observations_written=0,
                    created=True,
                )
            validate_transition("processing", "needs_distill")
            job_store.compare_and_set(
                job_id=job.id,
                expected_status="processing",
                expected_lease_owner=owner,
                updates={
                    "status": "needs_distill",
                    "lease_owner": None,
                    "lease_until": None,
                    "completed_at": datetime.now(timezone.utc),
                    "output_candidate_ids": [],
                },
            )
        except Exception as exc:
            # Failure during the defer transition is non-retryable: the
            # state machine rejected something or the store is broken.
            return _record_failure(
                job_store=job_store,
                job=job,
                stage="defer_to_agent",
                reason=str(exc),
                created=True,
            )
        refreshed = job_store.get(job.id) or job
        return ReflectionResult(
            job=refreshed,
            status="needs_distill",
            candidates_written=0,
            observations_written=0,
            created=True,
        )

    # ---- 8. Lease + execution path (Req 6.3, 6.4, 6.5, 9.x) -------------
    # No real pipeline is wired in v2.4.0; any non-defer mode falls
    # through to here. We still acquire a lease for symmetry with how
    # the real pipeline will work, then short-circuit to needs_distill
    # because there is nothing to execute. This satisfies Req 9.1 / 9.2
    # trivially (zero candidates written, zero confirmed truth touched).
    owner = f"reflection_once:{os.getpid()}"
    try:
        acquired = await acquire_lease(job_store, job.id, owner=owner)
    except Exception as exc:
        return _record_failure(
            job_store=job_store,
            job=job,
            stage="lease",
            reason=str(exc),
            created=True,
        )
    if not acquired:
        # Lost the race or already at max retries — surface as retryable
        # so the caller can poll / retry without blocking (Req 6.3).
        refreshed = job_store.get(job.id) or job
        return ReflectionResult(
            job=refreshed,
            status="retryable",
            candidates_written=0,
            observations_written=0,
            created=True,
        )

    # No real pipeline — transition processing → needs_distill so the
    # caller has a clean terminal-from-their-POV result.
    try:
        validate_transition("processing", "needs_distill")
        job_store.compare_and_set(
            job_id=job.id,
            expected_status="processing",
            expected_lease_owner=owner,
            updates={
                "status": "needs_distill",
                "lease_owner": None,
                "lease_until": None,
                "completed_at": datetime.now(timezone.utc),
                "output_candidate_ids": [],
            },
        )
    except Exception as exc:
        return _record_failure(
            job_store=job_store,
            job=job,
            stage="execute",
            reason=str(exc),
            created=True,
        )

    refreshed = job_store.get(job.id) or job
    return ReflectionResult(
        job=refreshed,
        status="needs_distill",
        candidates_written=0,
        observations_written=0,
        created=True,
    )


def _record_failure(
    *,
    job_store: ReflectionJobStore,
    job: ReflectionJob,
    stage: str,
    reason: str,
    created: bool,
    retryable: bool = False,
) -> ReflectionResult:
    """Persist a failure / retryable state and return a result (Req 6.3/6.4).

    If the failure save itself fails, we return a synthetic result with
    the original error rather than letting the secondary exception
    escape — Req 10.5 says reflection_once never raises.
    """
    target_status: Literal["retryable", "failed"] = (
        "retryable" if retryable else "failed"
    )
    error = f"{stage}: {reason}"
    try:
        job_store.compare_and_set(
            job_id=job.id,
            expected_status=job.status,
            expected_lease_owner=job.lease_owner,
            updates={
                "status": target_status,
                "error": error,
                "lease_owner": None,
                "lease_until": None,
            },
        )
    except Exception:
        # Secondary failure during error recording — fall through with
        # the original diagnostic.
        pass
    refreshed = None
    try:
        refreshed = job_store.get(job.id)
    except Exception:
        refreshed = None
    final = refreshed or job
    return ReflectionResult(
        job=final,
        status=target_status,
        candidates_written=0,
        observations_written=0,
        created=created,
    )
