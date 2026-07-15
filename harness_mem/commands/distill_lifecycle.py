"""Durable staging for Agent-led transcript distillation."""

from __future__ import annotations

from datetime import datetime, timezone
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
) -> list[ReflectionJob | SessionDistillJob]:
    """Return queued Agent work newest-first."""

    lossless_jobs: list[SessionDistillJob] = []
    for status in ("queued", "retryable", "processing", "reviewing"):
        lossless_jobs.extend(
            backend.transcript_store.list_distill_jobs(
                project_name=project_name,
                status=status,
                limit=100,
            )
        )
    legacy_jobs = backend.reflection_job_store.list(
        project_name=project_name,
        status="needs_distill",
        kind="reflection",
        limit=100,
    )
    return [*sorted(lossless_jobs, key=lambda item: item.created_at), *legacy_jobs]


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
) -> str:
    """Render private Agent instructions for queued evidence work."""

    if not jobs:
        return ""
    job_ids = ", ".join(job.id for job in jobs[:3])
    return "\n".join(
        [
            "# Pending Memory Maintenance  (Agent action)",
            f"{len(jobs)} transcript evidence task(s) await semantic distillation: {job_ids}",
            "Consume them now through the /hm:distill pipeline: call prepare_session_distill,",
            "read and submit every lossless chunk, review the complete session, write only",
            "warranted suggest_* candidates, then call finalize_session_distill.",
            "Legacy observations are audit-only and never count as a complete distill job.",
            "Do not tell the user the conversation was summarized until those steps finish.",
        ]
    )


__all__ = [
    "complete_pending_distill_jobs",
    "pending_distill_jobs",
    "render_pending_distill_instruction",
    "stage_distill_job",
]
