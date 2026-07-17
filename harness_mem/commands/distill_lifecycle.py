"""Durable staging for Agent-led transcript distillation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from typing import Iterable, Literal

from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

DistillSource = Literal["user", "agent", "ide_hook", "scheduler"]


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
        lossless_jobs,
        key=lambda item: item.created_at,
        reverse=recent_first,
    )
    selected: list[SessionDistillJob] = []
    for job in ordered:
        if len(selected) >= max(0, int(max_jobs)):
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
        job for job in completed if job.completed_at and job.completed_at >= current - timedelta(days=1)
    ]
    completed_7d = [
        job for job in completed if job.completed_at and job.completed_at >= current - timedelta(days=7)
    ]
    active = [job for job in jobs if job.status in {"queued", "processing", "reviewing"}]
    parked = [job for job in jobs if job.status == "parked"]
    retry_backoff = [
        job for job in jobs if job.retry_after is not None and job.retry_after > current
    ]
    oldest_parked = min((job.created_at for job in parked), default=None)
    budget_remaining = max(0, int(daily_job_budget) - len(offered_today))
    state = (
        "waiting_for_agent"
        if active and (budget_remaining > 0 or any(job.id in {item.id for item in offered_today} for job in active))
        else "daily_budget_exhausted"
        if active
        else "backoff"
        if retry_backoff
        else "idle"
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
        "throughput_per_day_7d": round(len(completed_7d) / 7, 2),
        "oldest_parked_age_hours": round(
            (current - oldest_parked).total_seconds() / 3600,
            1,
        )
        if oldest_parked is not None
        else 0.0,
        "recent_lane_selected": sum(job.drainer_lane == "recent" for job in jobs),
        "oldest_lane_selected": sum(job.drainer_lane == "oldest" for job in jobs),
        "agent_required": bool(active),
        "background_semantic_processing": False,
    }


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
    metrics: dict[str, Any] | None = None,
) -> str:
    """Render bounded automatic Agent work; no user command is required."""

    if not jobs:
        return ""
    selected = jobs[: max(1, max_jobs)]
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
            "Do this automatically without asking the user to run /hm:distill: call",
            "prepare_session_distill with",
            "evidence_mode=semantic, detail_level=compact, budget_tokens=3000; read the",
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


__all__ = [
    "complete_pending_distill_jobs",
    "distill_drainer_metrics",
    "pending_distill_jobs",
    "render_pending_distill_instruction",
    "stage_distill_job",
]
