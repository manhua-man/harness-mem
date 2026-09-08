"""Durable staging for Agent-led transcript distillation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any
from typing import Iterable, Literal

from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

DistillSource = Literal["user", "agent", "ide_hook", "scheduler"]
DEFAULT_DISTILL_BUDGET_TOKENS = 3000
MAX_STATUS_QUEUE_PREVIEW = 12


def stage_distill_job(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    observation_ids: Iterable[str],
    source: DistillSource,
) -> ReflectionJob | None:
    """Create one durable distill task unless the same evidence is active."""

    refs = list(dict.fromkeys(str(value) for value in observation_ids if value))
    if not refs:
        return None
    active = [
        *backend.reflection_job_store.list(
            project_name=project_name,
            status="needs_distill",
            kind="reflection",
        ),
        *backend.reflection_job_store.list(
            project_name=project_name,
            status="processing",
            kind="reflection",
        ),
    ]
    ref_set = set(refs)
    for job in active:
        if set(job.input_refs) == ref_set:
            return job

    job = ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        kind="reflection",
        phase="distill",
        status="needs_distill",
        source=source,
        input_refs=refs,
    )
    backend.reflection_job_store.save(job)
    return job


def pending_distill_jobs(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    recent_first: bool = True,
    max_jobs: int | None = None,
    record_offer: bool = True,
    now: datetime | None = None,
) -> list[ReflectionJob | SessionDistillJob]:
    """Return eligible Agent work in queue order.

    ``max_jobs`` is an optional caller choice.  Omitting it returns every
    eligible job; the runtime does not impose a daily processing quota.
    """

    current = now or datetime.now(timezone.utc)

    # Reconcile abandoned leases before lane selection. This only repairs
    # durable state; semantic work still requires the offered Agent job.
    backend.transcript_store.reconcile_distill_jobs(
        project_name=project_name,
        now=current,
        recovery_budget=3,
    )
    lossless_jobs: list[SessionDistillJob] = []
    for status in ("queued", "processing", "reviewing", "parked", "retryable"):
        lossless_jobs.extend(
            backend.transcript_store.list_distill_jobs(
                project_name=project_name,
                status=status,
            )
        )
    ordered = sorted(
        [
            job
            for job in lossless_jobs
            if not (
                job.status == "reviewing"
                and job.review_lease_owner
                and job.review_lease_until is not None
                and job.review_lease_until > current
            )
            and not (
                job.status == "retryable"
                and job.retry_after is not None
                and job.retry_after > current
            )
        ],
        key=lambda item: item.created_at,
        reverse=recent_first,
    )
    selected = ordered if max_jobs is None else ordered[: max(0, int(max_jobs))]
    selected = [
        (
            backend.transcript_store.activate_parked_distill_job_for_agent(
                job.id,
                offered_at=current,
            )
            if job.status == "parked"
            else job
        )
        for job in selected
    ]
    if record_offer and selected:
        backend.transcript_store.mark_distill_jobs_agent_offered(
            project_name,
            [job.id for job in selected],
            offered_at=current,
        )
    return list(selected)


def distill_drainer_metrics(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return truthful queue, backoff, fairness, and throughput state."""

    current = now or datetime.now(timezone.utc)
    jobs = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100000,
    )
    completed = [job for job in jobs if job.completed_at is not None]
    completed_24h = [
        job
        for job in completed
        if job.completed_at and job.completed_at >= current - timedelta(days=1)
    ]
    completed_7d = [
        job
        for job in completed
        if job.completed_at and job.completed_at >= current - timedelta(days=7)
    ]
    promoted_7d = [
        job for job in completed_7d if job.completion_disposition == "promoted"
    ]
    no_candidate_7d = [
        job for job in completed_7d if job.completion_disposition == "no_candidate"
    ]
    legacy_unknown_7d = [
        job for job in completed_7d if job.completion_disposition is None
    ]
    evidence_admission_7d = {
        "repository_verified": 0,
        "user_stated": 0,
        "unverified_blocked": 0,
        "contradicted": 0,
        "legacy_or_unknown": 0,
    }
    for job in completed_7d:
        admission = dict(job.promotion_summary.get("evidence_admission") or {})
        for key in evidence_admission_7d:
            evidence_admission_7d[key] += max(0, int(admission.get(key) or 0))
    cleanup_partial = [
        job for job in jobs if job.source_cleanup_status == "partial_failure"
    ]
    cleanup_unsupported = [
        job for job in jobs if job.source_cleanup_status == "unsupported"
    ]
    recovery_exhausted = [job for job in jobs if job.recovery_exhausted_at is not None]
    recovery_attempts = sum(max(0, int(job.recovery_count)) for job in jobs)
    recovery_timestamps = [
        job.last_recovery_at for job in jobs if job.last_recovery_at is not None
    ]
    stalled_progress = [
        job.last_progress_at
        for job in jobs
        if job.status in {"processing", "reviewing"}
        and isinstance(job.last_progress_at, datetime)
    ]
    active = [
        job for job in jobs if job.status in {"queued", "processing", "reviewing"}
    ]
    parked = [job for job in jobs if job.status == "parked"]
    retry_backoff = [
        job
        for job in jobs
        if job.status in {"queued", "retryable", "parked"}
        and job.retry_after is not None
        and job.retry_after > current
    ]
    retryable_ready = [
        job
        for job in jobs
        if job.status == "retryable"
        and (job.retry_after is None or job.retry_after <= current)
    ]
    oldest_parked = min((job.created_at for job in parked), default=None)
    autonomous_reviewing = [
        job
        for job in active
        if job.status == "reviewing"
        and job.review_execution_source == "autonomous_worker"
        and job.review_lease_owner
        and job.review_lease_until is not None
        and job.review_lease_until > current
    ]
    autonomous_completed = [
        job
        for job in completed
        if job.review_execution_source == "autonomous_worker"
        and job.completed_at is not None
    ]
    state = (
        "processing_autonomously"
        if autonomous_reviewing
        else "waiting_for_agent"
        if active
        else "backoff"
        if retry_backoff
        else "waiting_for_lane"
        if parked or retryable_ready
        else "idle"
    )
    pending_ids = {
        job.id for job in [*active, *parked, *retryable_ready, *retry_backoff]
    }
    pending_jobs = [job for job in jobs if job.id in pending_ids]
    pending_total = len(pending_ids)
    throughput_per_day = round(len(completed_7d) / 7, 2)
    stuck_reasons = _distill_stuck_reasons(
        state=state,
        active=len(active),
        parked=len(parked),
        retry_backoff=retry_backoff,
        retryable_ready=len(retryable_ready),
        throughput_per_day=throughput_per_day,
        pending_total=pending_total,
    )
    drain_estimate = _coarse_drain_estimate(
        pending_total=pending_total,
        active=len(active),
        parked=len(parked),
        retry_backoff_count=len(retry_backoff),
        throughput_per_day=throughput_per_day,
        state=state,
        retry_backoff=retry_backoff,
        current=current,
    )
    return {
        "state": state,
        "active": len(active),
        "parked": len(parked),
        "retry_backoff": len(retry_backoff),
        "offered_total": sum(job.agent_offer_day is not None for job in jobs),
        "completed_24h": len(completed_24h),
        "completed_7d": len(completed_7d),
        "promoted_7d": len(promoted_7d),
        "no_candidate_7d": len(no_candidate_7d),
        "legacy_unknown_7d": len(legacy_unknown_7d),
        "evidence_admission_7d": evidence_admission_7d,
        "source_cleanup_partial_failure": len(cleanup_partial),
        "source_cleanup_unsupported": len(cleanup_unsupported),
        "recovery_attempts_total": recovery_attempts,
        "recovery_exhausted": len(recovery_exhausted),
        "last_recovery_at": (
            max(recovery_timestamps).isoformat() if recovery_timestamps else None
        ),
        "oldest_stalled_age_hours": round(
            max(
                0.0,
                (current - min(stalled_progress)).total_seconds() / 3600,
            ),
            1,
        )
        if stalled_progress
        else 0.0,
        "throughput_per_day_7d": throughput_per_day,
        "oldest_parked_age_hours": round(
            (current - oldest_parked).total_seconds() / 3600,
            1,
        )
        if oldest_parked is not None
        else 0.0,
        "recent_lane_selected": sum(job.drainer_lane == "recent" for job in jobs),
        "oldest_lane_selected": sum(job.drainer_lane == "oldest" for job in jobs),
        "pending_total": pending_total,
        "queue_preview": _distill_queue_preview(
            backend,
            jobs=pending_jobs,
            now=current,
            queue_state=state,
        ),
        "stuck_reasons": stuck_reasons,
        "drain_estimate": drain_estimate,
        "agent_required": bool(pending_total),
        "background_semantic_processing": bool(
            autonomous_reviewing or autonomous_completed
        ),
        "autonomous_active": len(autonomous_reviewing),
        "last_semantic_success_at": (
            max(
                job.completed_at
                for job in autonomous_completed
                if job.completed_at is not None
            ).isoformat()
            if any(job.completed_at is not None for job in autonomous_completed)
            else None
        ),
    }


def _distill_queue_preview(
    backend: LocalMemoryBackend,
    *,
    jobs: list[SessionDistillJob],
    now: datetime,
    queue_state: str,
) -> list[dict[str, Any]]:
    """Project a bounded, ID-free lifecycle view of pending distill work.

    Status needs to answer which captured sessions are waiting and who is
    currently responsible without exposing transcript content, internal IDs,
    lease tokens, or filesystem locators.  A host session has no reliable
    user-authored title before it is distilled, so the stable human label is
    host plus capture time rather than a fabricated summary.
    """

    rank = {
        "reviewing": 0,
        "processing": 1,
        "queued": 2,
        "retryable": 3,
        "parked": 4,
    }
    ordered = sorted(
        jobs,
        key=lambda job: (
            rank.get(job.status, 99),
            job.created_at.astimezone(timezone.utc),
        ),
    )
    return [
        _distill_queue_item(backend, job=job, now=now, queue_state=queue_state)
        for job in ordered[:MAX_STATUS_QUEUE_PREVIEW]
    ]


def _distill_queue_item(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
    now: datetime,
    queue_state: str,
) -> dict[str, Any]:
    """Return one human-readable lifecycle row without internal identifiers."""

    live_owner = _live_distill_owner(backend, job=job, now=now)
    handler = _distill_handler_summary(
        job=job,
        live_owner=live_owner,
        queue_state=queue_state,
    )
    client_label = {
        "codex": "Codex",
        "codex-archive": "Codex archive",
        "claude-code": "Claude Code",
        "cursor": "Cursor",
    }.get(job.client, job.client or "Agent host")
    captured_at = job.created_at.astimezone(timezone.utc).isoformat()
    return {
        "project_name": job.project_name,
        "session_label": f"{client_label} session captured {captured_at}",
        "source_host": job.client,
        "captured_at": captured_at,
        "state": _distill_queue_state(job=job, live_owner=live_owner, queue_state=queue_state),
        "progress": {
            "completed_chunks": max(0, int(job.completed_chunk_count)),
            "expected_chunks": max(0, int(job.expected_chunk_count)),
        },
        "handler": handler,
    }


def _live_distill_owner(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
    now: datetime,
) -> str | None:
    """Return only a live lease owner; expired owners are not current agents."""

    if (
        job.status == "reviewing"
        and job.review_lease_owner
        and job.review_lease_until is not None
        and job.review_lease_until > now
    ):
        return job.review_lease_owner
    if job.status != "processing":
        return None
    for checkpoint in backend.transcript_store.list_distill_checkpoints(job.id):
        if (
            checkpoint.status == "processing"
            and checkpoint.lease_owner
            and checkpoint.lease_until is not None
            and checkpoint.lease_until > now
        ):
            return checkpoint.lease_owner
    return None


def _distill_handler_summary(
    *,
    job: SessionDistillJob,
    live_owner: str | None,
    queue_state: str,
) -> dict[str, str]:
    """Translate private lease mechanics into the responsible agent class."""

    owner = live_owner or ""
    if owner.startswith("autonomous:") or job.review_execution_source == "autonomous_worker":
        if live_owner:
            return {
                "kind": "autonomous_worker",
                "label": "harness-mem autonomous distill worker",
            }
    if owner.startswith("mcp-distill"):
        return {"kind": "interactive_agent", "label": "current MCP Agent"}
    if live_owner:
        return {"kind": "agent_worker", "label": "active Agent worker"}
    if job.status == "retryable":
        return {"kind": "waiting", "label": "waiting for a retry-capable Agent"}
    if job.status == "parked":
        return {"kind": "waiting", "label": "waiting for the next eligible Agent lane"}
    return {"kind": "waiting", "label": "waiting for a Codex Agent"}


def _distill_queue_state(
    *,
    job: SessionDistillJob,
    live_owner: str | None,
    queue_state: str,
) -> str:
    """Give the user-facing row a precise state, not only the global count."""

    if live_owner and job.status == "processing":
        return "processing_transcript"
    if live_owner and job.status == "reviewing":
        return "reviewing_session"
    if job.status == "retryable":
        return "waiting_for_retry"
    if job.status == "parked":
        return "waiting_for_lane"
    if job.status == "reviewing":
        return "waiting_for_review_agent"
    return "queued_for_agent"


def _distill_stuck_reasons(
    *,
    state: str,
    active: int,
    parked: int,
    retry_backoff: list[SessionDistillJob],
    retryable_ready: int,
    throughput_per_day: float,
    pending_total: int,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if retry_backoff:
        next_retry = min(
            job.retry_after for job in retry_backoff if job.retry_after is not None
        )
        reasons.append(
            {
                "code": "retry_backoff",
                "count": len(retry_backoff),
                "retry_after": next_retry.isoformat(),
                "action": "Retry after the reported time; continue healthy jobs first.",
            }
        )
    if retryable_ready and not active:
        reasons.append(
            {
                "code": "retryable_waiting_for_lane",
                "count": retryable_ready,
                "action": "Use hm in an Agent to refill the active lane.",
            }
        )
    if parked and not active:
        reasons.append(
            {
                "code": "parked_waiting_for_lane",
                "count": parked,
                "action": "Use hm in an Agent to refill the active lane.",
            }
        )
    if pending_total and throughput_per_day <= 0:
        reasons.append(
            {
                "code": "zero_7d_throughput",
                "count": pending_total,
                "action": "Complete one offered job with an Agent before estimating drain time.",
            }
        )
    return reasons


def _coarse_drain_estimate(
    *,
    pending_total: int,
    active: int,
    parked: int,
    retry_backoff_count: int,
    throughput_per_day: float,
    state: str,
    retry_backoff: list[SessionDistillJob],
    current: datetime,
) -> dict[str, Any]:
    """Estimate queue drain from observed Agent completions."""

    base: dict[str, Any] = {
        "pending_jobs": pending_total,
        "active_jobs": active,
        "parked_jobs": parked,
        "retry_backoff_jobs": retry_backoff_count,
        "observed_throughput_per_day_7d": throughput_per_day,
        "requires_agent_execution": pending_total > 0,
        "background_semantic_processing": False,
    }
    if pending_total == 0:
        return {**base, "status": "drained", "estimated_calendar_days": 0}
    if throughput_per_day <= 0:
        return {
            **base,
            "status": "unavailable",
            "reason": "zero_7d_throughput",
            "estimated_calendar_days": None,
        }

    effective_rate = throughput_per_day
    delay_days = 0
    latest_retry_after: datetime | None = None
    if retry_backoff:
        retry_times = [
            job.retry_after for job in retry_backoff if job.retry_after is not None
        ]
        if retry_times:
            latest_retry_after = max(retry_times)
            backoff_seconds = max(
                0.0,
                (latest_retry_after - current.astimezone(timezone.utc)).total_seconds(),
            )
            delay_days = max(delay_days, ceil(backoff_seconds / 86_400))
    estimated_days = delay_days + ceil(pending_total / effective_rate)
    estimate: dict[str, Any] = {
        **base,
        "status": "coarse_estimate",
        "effective_jobs_per_day": round(effective_rate, 2),
        "estimated_calendar_days": estimated_days,
        "basis": (
            "latest retry backoff plus observed 7d Agent throughput"
            if latest_retry_after is not None
            else "observed 7d Agent throughput"
        ),
    }
    if retry_backoff:
        estimate["next_retry_after"] = min(
            job.retry_after for job in retry_backoff if job.retry_after is not None
        ).isoformat()
    if latest_retry_after is not None:
        estimate["latest_retry_after"] = latest_retry_after.isoformat()
    return estimate


def complete_pending_distill_jobs(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidate_ids: Iterable[str] = (),
    job_id: str | None = None,
) -> list[ReflectionJob]:
    """Complete one explicit legacy job, or the sole processing job."""

    completed: list[ReflectionJob] = []
    output_ids = list(dict.fromkeys(str(value) for value in candidate_ids if value))
    now = datetime.now(timezone.utc)
    jobs = backend.reflection_job_store.list(
        project_name=project_name,
        status="processing",
        kind="reflection",
    )
    if job_id is not None:
        jobs = [job for job in jobs if job.id == job_id]
    elif len(jobs) != 1:
        return []
    for job in jobs:
        job.phase = "done"
        job.status = "completed"
        job.output_candidate_ids = output_ids
        job.completed_at = now
        backend.reflection_job_store.save(job)
        completed.append(job)
    return completed


def render_pending_distill_instruction(
    jobs: list[ReflectionJob | SessionDistillJob],
    *,
    max_jobs: int | None = None,
    budget_tokens: int = DEFAULT_DISTILL_BUDGET_TOKENS,
    metrics: dict[str, Any] | None = None,
) -> str:
    """Render automatic Agent work; no user command is required."""

    if not jobs:
        return ""
    selected = jobs if max_jobs is None else jobs[: max(0, int(max_jobs))]
    if not selected:
        return ""
    job_ids = ", ".join(job.id for job in selected)
    queue = metrics or {}
    return "\n".join(
        [
            "# Automatic Memory Maintenance  (private Agent action)",
            f"State: {queue.get('state', 'waiting_for_agent')}; Agent execution is required.",
            f"Queue: active={queue.get('active', len(jobs))}, parked={queue.get('parked', 0)}, retry_backoff={queue.get('retry_backoff', 0)}.",
            f"Process the available jobs now: {job_ids}",
            "Process each selected session independently; do not create a second queue or daily quota.",
            "Do this automatically without asking the user to start another memory action.",
            "Process the selected ids sequentially, in the order shown.",
            "For each selected id, call prepare_session_distill with",
            "distill_job_id=<selected id>, evidence_mode=semantic,",
            f"detail_level=compact, budget_tokens={max(1, int(budget_tokens))}, run_ingest=false; read the",
            "indexed manifest, select semantic windows, then drill into raw proof only",
            "when a candidate needs it. Review the complete session and write only",
            "warranted govern_memory(action=suggest) candidates, then call finalize_session_distill.",
            "If one job fails, call prepare_session_distill with defer_job_id and defer_reason,",
            "then continue with the next selected id;",
            "a broken historical session must not block current work or later jobs.",
            "Legacy observations are audit-only and never count as a complete distill job.",
            "Do not tell the user the conversation was summarized until those steps finish.",
        ]
    )


def build_distill_maintenance_offer(
    jobs: list[ReflectionJob | SessionDistillJob],
    *,
    max_jobs: int | None = None,
    budget_tokens: int = DEFAULT_DISTILL_BUDGET_TOKENS,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the machine-readable contract for one Agent-active wake.

    The offer does not perform semantic work. It gives the current Agent the
    exact job ids and shared prepare parameters so host skills do not have to
    scrape ids from rendered wake text.
    """

    selected = jobs if max_jobs is None else jobs[: max(0, int(max_jobs))]
    job_ids = [job.id for job in selected]
    normalized_budget = max(1, int(budget_tokens))
    prepare_arguments = {
        "run_ingest": False,
        "evidence_mode": "semantic",
        "detail_level": "compact",
        "budget_tokens": normalized_budget,
    }
    per_job_failure_policy = {
        "on_failure": "defer_job",
        "on_owned_failure": "defer_job",
        "on_busy": "skip_without_defer",
        "on_completed_finalize_retry": "replay_finalize",
        "continue_with_next": True,
    }
    queue = metrics or {}
    return {
        "contract_version": "agent-distill-offer-v2",
        "agent_execution_required": bool(selected),
        "user_confirmation_required": False,
        "process_limit": len(selected),
        "job_ids": job_ids,
        # Compatibility for consumers that only understand a single job.
        "distill_job_id": job_ids[0] if job_ids else None,
        "execution_order": "sequential",
        "prepare_arguments": prepare_arguments,
        "budget": {
            "scope": "complete_serialized_responses",
            "per_job_target_tokens": normalized_budget,
            "maximum_jobs": len(selected),
            "maximum_target_tokens": normalized_budget * len(selected),
        },
        "failure_policy": "defer_and_continue",
        "per_job_failure_policy": per_job_failure_policy,
        "jobs": [
            {
                "distill_job_id": job_id,
                "ordinal": index,
                "prepare_arguments": {
                    **prepare_arguments,
                    "distill_job_id": job_id,
                },
                "failure_policy": dict(per_job_failure_policy),
            }
            for index, job_id in enumerate(job_ids, start=1)
        ],
        "queue": {
            "state": queue.get("state", "idle"),
            "active": int(queue.get("active", len(jobs)) or 0),
            "parked": int(queue.get("parked", 0) or 0),
            "retry_backoff": int(queue.get("retry_backoff", 0) or 0),
            "offered_total": int(queue.get("offered_total", 0) or 0),
        },
        "instruction": render_pending_distill_instruction(
            jobs,
            max_jobs=max_jobs,
            budget_tokens=normalized_budget,
            metrics=metrics,
        ),
    }


__all__ = [
    "complete_pending_distill_jobs",
    "build_distill_maintenance_offer",
    "distill_drainer_metrics",
    "pending_distill_jobs",
    "render_pending_distill_instruction",
    "stage_distill_job",
]
