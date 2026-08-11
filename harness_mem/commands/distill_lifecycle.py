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
MAX_DISTILL_JOBS_PER_OFFER = 3
DEFAULT_DISTILL_BUDGET_TOKENS = 3000


def _bounded_job_limit(max_jobs: int) -> int:
    """Clamp every offer path to the shared, sequential batch safety limit."""

    return min(MAX_DISTILL_JOBS_PER_OFFER, max(0, int(max_jobs)))


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
            limit=100,
        ),
        *backend.reflection_job_store.list(
            project_name=project_name,
            status="processing",
            kind="reflection",
            limit=100,
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
    target_backlog: int = 2,
    max_jobs: int = 2,
    daily_job_budget: int = 8,
    record_offer: bool = True,
    now: datetime | None = None,
) -> list[ReflectionJob | SessionDistillJob]:
    """Return bounded Agent-active work without exceeding the daily new-job budget."""

    current = now or datetime.now(timezone.utc)

    # Reconcile abandoned leases before lane selection. This only repairs
    # durable state; semantic work still requires the offered Agent job.
    backend.transcript_store.reconcile_distill_jobs(
        project_name=project_name,
        now=current,
        recovery_budget=3,
    )
    backend.transcript_store.rebalance_distill_jobs(
        project_name,
        target_active=target_backlog,
        recent_first=recent_first,
    )

    lossless_jobs: list[SessionDistillJob] = []
    for status in ("queued", "processing", "reviewing"):
        lossless_jobs.extend(
            backend.transcript_store.list_distill_jobs(
                project_name=project_name,
                status=status,
                limit=100,
            )
        )
    all_jobs = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100000,
    )
    today = current.date().isoformat()
    offered_today = {job.id for job in all_jobs if job.agent_offer_day == today}
    remaining = max(0, int(daily_job_budget) - len(offered_today))
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
        ],
        key=lambda item: item.created_at,
        reverse=recent_first,
    )
    job_limit = _bounded_job_limit(max_jobs)
    selected: list[SessionDistillJob] = []
    for job in ordered:
        if len(selected) >= job_limit:
            break
        if job.id in offered_today:
            selected.append(job)
            continue
        if remaining <= 0:
            continue
        selected.append(job)
        remaining -= 1
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
    daily_job_budget: int = 8,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return truthful queue, budget, backoff, fairness, and throughput state."""

    current = now or datetime.now(timezone.utc)
    jobs = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100000,
    )
    today = current.date().isoformat()
    offered_today = [job for job in jobs if job.agent_offer_day == today]
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
    budget_remaining = max(0, int(daily_job_budget) - len(offered_today))
    offered_active_ids = {job.id for job in active if job.agent_offer_day == today}
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
        if active and (budget_remaining > 0 or bool(offered_active_ids))
        else "daily_budget_exhausted"
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
        daily_job_budget=int(daily_job_budget),
        daily_budget_remaining=budget_remaining,
        state=state,
        retry_backoff=retry_backoff,
        current=current,
    )
    return {
        "state": state,
        "active": len(active),
        "parked": len(parked),
        "retry_backoff": len(retry_backoff),
        "offered_today": len(offered_today),
        "daily_job_budget": int(daily_job_budget),
        "daily_budget_remaining": budget_remaining,
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
        "stuck_reasons": stuck_reasons,
        "drain_estimate": drain_estimate,
        "agent_required": bool(pending_total),
        "background_semantic_processing": bool(
            autonomous_reviewing or autonomous_completed
        ),
        "autonomous_active": len(autonomous_reviewing),
        "last_semantic_success_at": (
            max(job.completed_at for job in autonomous_completed).isoformat()
            if autonomous_completed
            else None
        ),
    }


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
    if state == "daily_budget_exhausted":
        reasons.append(
            {
                "code": "daily_budget_exhausted",
                "count": active,
                "action": "Resume on the next UTC budget day; already offered jobs remain runnable.",
            }
        )
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
                "action": "Run an Agent-capable wake or /hm:distill to refill the active lane.",
            }
        )
    if parked and not active:
        reasons.append(
            {
                "code": "parked_waiting_for_lane",
                "count": parked,
                "action": "Run an Agent-capable wake or /hm:distill to refill the active lane.",
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
    daily_job_budget: int,
    daily_budget_remaining: int,
    state: str,
    retry_backoff: list[SessionDistillJob],
    current: datetime,
) -> dict[str, Any]:
    """Estimate queue drain conservatively from observed Agent completions and budget."""

    base: dict[str, Any] = {
        "pending_jobs": pending_total,
        "active_jobs": active,
        "parked_jobs": parked,
        "retry_backoff_jobs": retry_backoff_count,
        "observed_throughput_per_day_7d": throughput_per_day,
        "daily_job_budget": max(0, daily_job_budget),
        "daily_budget_remaining": daily_budget_remaining,
        "requires_agent_execution": pending_total > 0,
        "background_semantic_processing": False,
    }
    if pending_total == 0:
        return {**base, "status": "drained", "estimated_calendar_days": 0}
    if throughput_per_day <= 0 or daily_job_budget <= 0:
        reason = (
            "zero_7d_throughput" if throughput_per_day <= 0 else "zero_daily_budget"
        )
        return {
            **base,
            "status": "unavailable",
            "reason": reason,
            "estimated_calendar_days": None,
        }

    effective_rate = min(throughput_per_day, float(daily_job_budget))
    delay_days = 1 if state == "daily_budget_exhausted" else 0
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
            "latest retry backoff plus min(observed 7d Agent throughput, "
            "daily new-job budget)"
            if latest_retry_after is not None
            else "min(observed 7d Agent throughput, daily new-job budget)"
        ),
    }
    if delay_days:
        next_budget_day = (
            (current.astimezone(timezone.utc) + timedelta(days=1)).date().isoformat()
        )
        estimate["starts_after"] = f"{next_budget_day}T00:00:00+00:00"
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
        limit=100,
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
    max_jobs: int = 2,
    target_backlog: int = 2,
    budget_tokens: int = DEFAULT_DISTILL_BUDGET_TOKENS,
    metrics: dict[str, Any] | None = None,
) -> str:
    """Render bounded automatic Agent work; no user command is required."""

    if not jobs:
        return ""
    selected = jobs[: _bounded_job_limit(max_jobs)]
    if not selected:
        return ""
    job_ids = ", ".join(job.id for job in selected)
    queue = metrics or {}
    return "\n".join(
        [
            "# Automatic Memory Maintenance  (private Agent action)",
            f"State: {queue.get('state', 'waiting_for_agent')}; Agent execution is required.",
            f"Queue: active={queue.get('active', len(jobs))}, parked={queue.get('parked', 0)}, retry_backoff={queue.get('retry_backoff', 0)}.",
            f"Daily new-job budget: {queue.get('offered_today', len(selected))}/{queue.get('daily_job_budget', len(selected))}; process up to {len(selected)} now: {job_ids}",
            "Fair refill policy: three recent jobs, then one oldest eligible job.",
            f"Steady-state target: at most {max(0, target_backlog)} queued task(s).",
            "Older cold evidence is parked, not deleted, and refills this active lane after completion.",
            "Do this automatically without asking the user to run /hm:distill.",
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
    max_jobs: int = 2,
    target_backlog: int = 2,
    budget_tokens: int = DEFAULT_DISTILL_BUDGET_TOKENS,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the machine-readable contract for one Agent-active wake.

    The offer does not perform semantic work.  It gives the current Agent the
    exact bounded job ids and shared prepare parameters so host skills do not
    have to scrape ids from rendered wake text.
    """

    selected = jobs[: _bounded_job_limit(max_jobs)]
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
            "offered_today": int(queue.get("offered_today", len(selected)) or 0),
            "daily_job_budget": int(queue.get("daily_job_budget", len(selected)) or 0),
            "target_active": max(0, int(target_backlog)),
        },
        "instruction": render_pending_distill_instruction(
            jobs,
            max_jobs=max_jobs,
            target_backlog=target_backlog,
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
