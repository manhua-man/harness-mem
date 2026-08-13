"""Durable autonomous distill runner used by detached host workers."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator, Protocol
from uuid import uuid4

from harness_mem.autonomous.models import (
    DistillCandidate,
)
from harness_mem.autonomous.provider import (
    ProviderError,
    ProviderResult,
    ResponsesApiProvider,
)
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.session_distill import (
    SessionDistillJob,
    ZeroCandidateChallenge as RuntimeZeroCandidateChallenge,
)
from harness_mem.hook_receipts import hook_configuration_fingerprint
from harness_mem.session_notes import (
    existing_session_note_path,
    is_meaningful_session_summary,
    materialize_session_note,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


logger = logging.getLogger("harness_mem.autonomous")
_REVIEW_LEASE_SECONDS = 300
_RUNTIME_SOURCE_FILES = (
    Path(__file__),
    Path(__file__).with_name("models.py"),
    Path(__file__).with_name("provider.py"),
    Path(__file__).parents[1] / "host_entry" / "__main__.py",
    Path(__file__).parents[1] / "hook_background.py",
    Path(__file__).parents[1] / "commands" / "maintenance.py",
    Path(__file__).parents[1] / "commands" / "distill_lifecycle.py",
    Path(__file__).parents[1] / "mcp" / "distill_handlers.py",
    Path(__file__).parents[1] / "storage" / "session_distill_store.py",
    Path(__file__).parents[1] / "storage" / "transcript_store.py",
    Path(__file__).parents[1] / "core" / "schemas" / "session_distill.py",
    Path(__file__).parents[1] / "session_notes.py",
)


class DistillProvider(Protocol):
    name: str

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Any = None,
    ) -> ProviderResult: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def autonomous_runtime_fingerprint() -> str:
    """Fingerprint the runtime files whose behavior the receipt claims."""

    digest = hashlib.sha256()
    for path in _RUNTIME_SOURCE_FILES:
        digest.update(str(path.name).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def autonomous_config_fingerprint(config: MergedConfig) -> str:
    """Fingerprint the effective settings that control autonomous execution."""

    payload = {
        "enabled": config.distill_autonomous_enabled,
        "max_jobs_per_wake": config.distill_auto_max_jobs_per_wake,
        "daily_job_budget": config.distill_auto_daily_job_budget,
        "target_backlog": config.distill_auto_target_backlog,
        "recent_first": config.distill_auto_recent_first,
        "budget_tokens": config.cost_budget_distill_tokens,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def autonomous_receipt_path(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> Path:
    key = hashlib.sha256(
        f"{project_name}\0{project_root.expanduser().resolve()}".encode("utf-8")
    ).hexdigest()[:24]
    return Path(data_dir) / "autonomous" / "receipts" / f"{key}.json"


def read_autonomous_receipt(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> dict[str, Any] | None:
    path = autonomous_receipt_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _legacy_verified_completion(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Recover one self-contained success snapshot from a complete v2/v3 receipt."""

    if int(receipt.get("schema_version") or 0) not in {2, 3}:
        return None
    trigger_id = str(receipt.get("trigger_id") or "")
    batch = receipt.get("batch")
    jobs = batch.get("jobs", []) if isinstance(batch, dict) else []
    record = next(
        (
            item
            for item in jobs
            if isinstance(item, dict)
            and item.get("status") == "completed"
            and str(item.get("session_id") or "") == trigger_id
            and isinstance(item.get("provider"), dict)
            and isinstance(item.get("note"), dict)
            and item.get("last_semantic_success_at")
            and item.get("last_job_completed_at")
            and item.get("last_note_materialized_at")
        ),
        None,
    )
    if record is None:
        return None
    return {
        "schema_version": 1,
        "trigger_id": trigger_id,
        "client": receipt.get("client"),
        "execution_source": receipt.get("execution_source"),
        "hook_launch_verified": receipt.get("hook_launch_verified") is True,
        "hook_config_fingerprint": receipt.get("hook_config_fingerprint"),
        "runtime_fingerprint": receipt.get("runtime_fingerprint"),
        "config_fingerprint": receipt.get("config_fingerprint"),
        "hook_reentry_count": int(receipt.get("hook_reentry_count") or 0),
        "job_id": record.get("job_id"),
        "session_id": record.get("session_id"),
        "last_semantic_success_at": record.get("last_semantic_success_at"),
        "last_job_completed_at": record.get("last_job_completed_at"),
        "last_note_materialized_at": record.get("last_note_materialized_at"),
        "provider": record.get("provider"),
        "note": record.get("note"),
    }


def _write_receipt(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    update: dict[str, Any],
) -> dict[str, Any]:
    path = autonomous_receipt_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    previous = (
        read_autonomous_receipt(
            data_dir,
            project_name=project_name,
            project_root=project_root,
        )
        or {}
    )
    preserved_completion = previous.get("last_verified_completion")
    if not isinstance(preserved_completion, dict):
        preserved_completion = _legacy_verified_completion(previous)
    payload = {
        **previous,
        "schema_version": 4,
        "project_name": project_name,
        "project_root": str(project_root.expanduser().resolve()),
        **(
            {"last_verified_completion": preserved_completion}
            if preserved_completion is not None
            else {}
        ),
        **update,
        "heartbeat_at": _now(),
        "worker_pid": os.getpid(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return payload


@contextmanager
def _tool_bindings(backend: LocalMemoryBackend) -> Iterator[Any]:
    from harness_mem.mcp import tool_handlers

    old_backend = getattr(tool_handlers, "_backend_provider", None)
    old_observer = getattr(tool_handlers, "_observer_data_dir_provider", None)
    old_budgets = getattr(tool_handlers, "_cost_surface_budgets_provider", None)
    old_logger = getattr(tool_handlers, "logger", logger)
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logger,
    )
    try:
        yield tool_handlers
    finally:
        if old_backend is None or old_observer is None or old_budgets is None:
            tool_handlers.reset_tool_handler_dependencies()
        else:
            tool_handlers.configure_tool_handler_dependencies(
                backend_provider=old_backend,
                observer_data_dir=old_observer,
                cost_surface_budgets=old_budgets,
                logger_instance=old_logger,
            )


def run_autonomous_distill_batch(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider | None = None,
    notes_dir: Path | None = None,
    max_jobs: int | None = None,
    preferred_job_id: str | None = None,
    launch_source: str | None = None,
) -> dict[str, Any]:
    """Process a bounded offered batch and materialize user-visible notes."""

    from harness_mem.maintenance_lock import maintenance_is_locked

    if launch_source != "archive_batch" and maintenance_is_locked(backend.data_dir):
        return {
            "success": False,
            "state": "busy",
            "reason": "exclusive_maintenance_run_active",
            "outcomes": [],
        }

    root = Path(project_root).expanduser().resolve()
    selected_limit = min(
        3,
        max(1, int(max_jobs or config.distill_auto_max_jobs_per_wake)),
    )
    # Distillation is bounded structured classification, not a coding turn.
    # Keep it independent from the user's heavier interactive model so a main
    # Agent model change cannot silently reintroduce provider latency.
    chosen_provider = provider or ResponsesApiProvider()
    resolved_notes = notes_dir or Path.home() / ".codex" / "hm-distill" / "sessions"
    runtime_dir = Path(backend.data_dir) / "autonomous" / "provider-runtime"
    started_at = _now()
    _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": "running",
            "started_at": started_at,
            "trigger_id": trigger_id,
            "client": client,
            "execution_source": "autonomous_worker",
            "hook_launch_verified": bool(
                launch_source == "ide_hook" and trigger_id and client
            ),
            "hook_config_fingerprint": hook_configuration_fingerprint(
                root,
                client=client,
            ),
            "provider_name": chosen_provider.name,
            "runtime_fingerprint": autonomous_runtime_fingerprint(),
            "config_fingerprint": autonomous_config_fingerprint(config),
            "hook_reentry_count": 0,
            "batch": {
                "offered": 0,
                "attempted": 0,
                "completed": 0,
                "deferred": 0,
                "busy": 0,
                "job_ids": [],
                "jobs": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "provider_seconds": 0.0,
            },
            "finished_at": None,
            "job_id": None,
            "session_id": None,
            "provider": None,
            "note": None,
            "last_semantic_success_at": None,
            "last_job_completed_at": None,
            "last_note_materialized_at": None,
            "error": None,
        },
    )
    outcomes: list[dict[str, Any]] = []
    _repair_missing_notes(
        backend,
        project_name=project_name,
        project_root=root,
        notes_dir=resolved_notes,
    )
    backlog_limit = selected_limit - (1 if preferred_job_id else 0)
    jobs = pending_distill_jobs(
        backend,
        project_name=project_name,
        recent_first=config.distill_auto_recent_first,
        target_backlog=config.distill_auto_target_backlog,
        max_jobs=max(0, backlog_limit),
        daily_job_budget=config.distill_auto_daily_job_budget,
        record_offer=True,
    )
    preferred = (
        backend.transcript_store.get_distill_job(preferred_job_id)
        if preferred_job_id
        else None
    )
    if preferred is not None and _preferred_job_is_eligible(
        preferred, project_name=project_name, trigger_id=trigger_id
    ):
        jobs = [preferred, *(job for job in jobs if job.id != preferred.id)]
    jobs = jobs[:selected_limit]
    with _tool_bindings(backend) as tools:
        for offered in jobs:
            if not isinstance(offered, SessionDistillJob):
                continue
            outcome = _run_one(
                backend,
                tools=tools,
                job_id=offered.id,
                project_name=project_name,
                project_root=root,
                config=config,
                trigger_id=trigger_id,
                client=client,
                provider=chosen_provider,
                runtime_dir=runtime_dir,
                notes_dir=resolved_notes,
            )
            outcomes.append(outcome)
            if offered.id == preferred_job_id:
                outcome["selection_reason"] = "trigger_session"

    succeeded = [item for item in outcomes if item["status"] == "completed"]
    deferred = [item for item in outcomes if item["status"] == "deferred"]
    busy = [item for item in outcomes if item["status"] == "busy"]
    state = (
        "partial"
        if succeeded and deferred
        else "succeeded"
        if succeeded
        else "deferred"
        if deferred
        else "busy"
        if busy
        else "idle"
    )
    latest_success = succeeded[-1] if succeeded else None
    latest_semantic_success = next(
        (
            item
            for item in reversed(succeeded)
            if item.get("last_semantic_success_at") and item.get("provider")
        ),
        None,
    )
    latest_evidence = latest_semantic_success or latest_success
    latest_error = deferred[-1].get("error") if deferred else None
    receipt = _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": state,
            "finished_at": _now(),
            "trigger_id": trigger_id,
            "batch": {
                "offered": len(jobs),
                "attempted": len(outcomes),
                "completed": len(succeeded),
                "deferred": len(deferred),
                "busy": len(busy),
                "job_ids": [item["job_id"] for item in outcomes],
                "jobs": outcomes,
                "input_tokens": sum(
                    int((item.get("provider") or {}).get("input_tokens") or 0)
                    for item in outcomes
                ),
                "output_tokens": sum(
                    int((item.get("provider") or {}).get("output_tokens") or 0)
                    for item in outcomes
                ),
                "total_tokens": sum(
                    int((item.get("provider") or {}).get("total_tokens") or 0)
                    for item in outcomes
                ),
                "provider_seconds": round(
                    sum(
                        float(
                            (item.get("provider") or {}).get("duration_seconds") or 0.0
                        )
                        for item in outcomes
                    ),
                    3,
                ),
            },
            # These compatibility fields deliberately come from one job record.
            # Consumers needing a specific job must read batch.jobs[].
            "job_id": latest_evidence.get("job_id") if latest_evidence else None,
            "session_id": (
                latest_evidence.get("session_id") if latest_evidence else None
            ),
            "provider": latest_evidence.get("provider") if latest_evidence else None,
            "note": latest_evidence.get("note") if latest_evidence else None,
            "last_semantic_success_at": (
                latest_evidence.get("last_semantic_success_at")
                if latest_evidence
                else None
            ),
            "last_job_completed_at": (
                latest_evidence.get("last_job_completed_at")
                if latest_evidence
                else None
            ),
            "last_note_materialized_at": (
                latest_evidence.get("last_note_materialized_at")
                if latest_evidence
                else None
            ),
            "error": None if latest_success else latest_error,
            "last_batch_error": latest_error,
        },
    )
    return {
        "success": bool(succeeded) or not outcomes,
        "state": state,
        "outcomes": outcomes,
        "receipt": receipt,
    }


def _preferred_job_is_eligible(
    job: SessionDistillJob | None,
    *,
    project_name: str,
    trigger_id: str | None,
) -> bool:
    """Keep the trigger job selected after queue reconciliation advances it."""

    return bool(
        job is not None
        and job.project_name == project_name
        and job.session_id == trigger_id
        and job.status
        in {"queued", "parked", "processing", "reviewing", "retryable"}
    )


def _run_one(
    backend: LocalMemoryBackend,
    *,
    tools: Any,
    job_id: str,
    project_name: str,
    project_root: Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider,
    runtime_dir: Path,
    notes_dir: Path,
) -> dict[str, Any]:
    lease_owner = f"autonomous:{os.getpid()}:{uuid4()}"
    try:
        packet = tools.tool_prepare_session_distill(
            project_name=project_name,
            client="auto",
            scope="project",
            project_root=str(project_root),
            distill_job_id=job_id,
            evidence_mode="semantic",
            detail_level="compact",
            budget_tokens=config.cost_budget_distill_tokens,
            run_ingest=False,
            _distill_source="autonomous_worker",
        )
        if not packet.get("success"):
            raise ProviderError(
                str(packet.get("error") or "semantic prepare failed"),
                kind="transient",
            )
        job = backend.transcript_store.get_distill_job(job_id)
        if job is None:
            raise ProviderError(
                "prepared distill job disappeared", kind="unrecoverable"
            )
        if job.status == "completed":
            note = _materialize_note(job, notes_dir=notes_dir)
            completion = _record_success_receipt(
                backend,
                project_name=project_name,
                project_root=project_root,
                trigger_id=trigger_id,
                client=client,
                job=job,
                note=note,
                provider_receipt=None,
            )
            return {
                "job_id": job.id,
                "session_id": job.session_id,
                "status": "completed",
                "repaired": True,
                "note": note,
                "provider": None,
                **completion,
            }
        claimed = backend.transcript_store.claim_distill_review(
            job_id,
            lease_owner=lease_owner,
            execution_source="autonomous_worker",
            lease_seconds=_REVIEW_LEASE_SECONDS,
        )
        if claimed is None:
            return {"job_id": job_id, "session_id": job.session_id, "status": "busy"}
        session_id = job.session_id

        def heartbeat() -> None:
            if not backend.transcript_store.renew_distill_review_lease(
                job_id,
                lease_owner=lease_owner,
                lease_seconds=_REVIEW_LEASE_SECONDS,
            ):
                raise ProviderError("semantic review lease was lost", kind="transient")
            try:
                from harness_mem.hook_background import heartbeat_background_worker

                heartbeat_background_worker(
                    backend.data_dir,
                    project_root=project_root,
                    client=client,
                )
            except Exception:
                logger.warning(
                    "could not renew detached worker heartbeat", exc_info=True
                )
            _write_receipt(
                backend.data_dir,
                project_name=project_name,
                project_root=project_root,
                update={
                    "state": "running",
                    "job_id": job_id,
                    "session_id": session_id,
                },
            )

        provider_result, decision, validated_candidates, candidate_warnings = (
            _decide_with_candidate_retry(
                provider,
                manifest=build_provider_manifest(packet),
                packet=packet,
                job=job,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        )
        governed_count = 0
        for _candidate, arguments in validated_candidates:
            governed = tools.tool_govern_memory(action="suggest", arguments=arguments)
            if not governed.get("success"):
                raise ProviderError(
                    str(governed.get("error") or "candidate governance failed"),
                    kind="unrecoverable",
                )
            governed_count += 1
        if decision.candidates and governed_count == 0:
            raise ProviderError(
                "All provider candidates failed kind-specific validation: "
                + "; ".join(candidate_warnings)[:1000],
                kind="unrecoverable",
            )
        handoff = _govern_unfinished_handoff(
            tools,
            job=job,
            decision=decision,
        )
        finalized = tools.tool_finalize_session_distill(
            project_name=project_name,
            job_id=job_id,
            semantic_review=decision.semantic_review.model_dump(
                mode="json", exclude_none=True
            ),
            _review_lease_owner=lease_owner,
        )
        if not finalized.get("success"):
            raise ProviderError(
                str(
                    finalized.get("error")
                    or finalized.get("reason_codes")
                    or "finalize failed"
                ),
                kind="unrecoverable",
            )
        stored = backend.transcript_store.get_distill_job(job_id)
        if stored is None or stored.status != "completed":
            raise ProviderError(
                "finalize did not persist a completed job", kind="unrecoverable"
            )
        # Combine the pre-cleanup identity with the completed, sanitized
        # result only in memory. This preserves a useful user-facing Note in
        # the caller's requested directory without restoring identifiers to
        # the durable raw-evidence ledger.
        note_job = stored.model_copy(
            update={
                "session_id": job.session_id,
                "project_root": job.project_root,
                "semantic_review": decision.semantic_review.model_dump(
                    mode="json", exclude_none=True
                ),
            }
        )
        note = _materialize_note(note_job, notes_dir=notes_dir)
        provider_receipt = {
            **provider_result.receipt(),
            "job_id": stored.id,
            "source_revision": job.source_revision,
            "session_id_sha256": _identity_digest(job.session_id),
            "trigger_id_sha256": _identity_digest(trigger_id),
            "project_root_sha256": _identity_digest(str(project_root)),
        }
        completion = _record_success_receipt(
            backend,
            project_name=project_name,
            project_root=project_root,
            trigger_id=trigger_id,
            client=client,
            job=note_job,
            note=note,
            provider_receipt=provider_receipt,
        )
        return {
            "job_id": note_job.id,
            "session_id": note_job.session_id,
            "status": "completed",
            "note_path": note["path"],
            "note": note,
            "provider": provider_receipt,
            "handoff": handoff,
            "candidate_warnings": candidate_warnings,
            **completion,
        }
    except ProviderError as exc:
        job = backend.transcript_store.get_distill_job(job_id)
        if job is not None and job.review_lease_owner == lease_owner:
            job = backend.transcript_store.defer_distill_job(
                job_id,
                error=f"{exc.kind}: {exc}"[:512],
            )
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={
                "state": "deferred",
                "job_id": job_id,
                "session_id": job.session_id if job else None,
                "error": {
                    "kind": exc.kind,
                    "message": str(exc)[:1000],
                    "exit_code": exc.exit_code,
                },
            },
        )
        return {
            "job_id": job_id,
            "session_id": job.session_id if job else None,
            "status": "deferred",
            "error": {"kind": exc.kind, "message": str(exc)[:1000]},
        }
    except Exception as exc:  # noqa: BLE001 - one broken job must not block the batch.
        job = backend.transcript_store.get_distill_job(job_id)
        if job is not None and job.review_lease_owner == lease_owner:
            backend.transcript_store.defer_distill_job(
                job_id,
                error=f"unrecoverable: {type(exc).__name__}: {exc}"[:512],
            )
        logger.exception("autonomous distill job failed: %s", job_id)
        return {
            "job_id": job_id,
            "session_id": job.session_id if job else None,
            "status": "deferred",
            "error": {
                "kind": "unrecoverable",
                "message": f"{type(exc).__name__}: {exc}"[:1000],
            },
        }


def _govern_unfinished_handoff(
    tools: Any,
    *,
    job: SessionDistillJob,
    decision: Any,
) -> dict[str, Any] | None:
    """Persist partial-session work under the same distill job boundary."""

    review = decision.semantic_review
    unfinished = [
        str(item).strip()
        for item in review.unfinished_work
        if str(item).strip()
    ]
    if review.promotion_decision != "partial" or not unfinished:
        return None
    result = tools.tool_govern_memory(
        action="handoff",
        arguments={
            "project_name": job.project_name,
            "task_id": f"distill-follow-up-{job.id}",
            "summary": str(review.final_outcome).strip()[:1000],
            "status": "in_progress",
            "next_steps": unfinished,
            "blockers": [],
            "distill_job_id": job.id,
        },
    )
    if not result.get("success"):
        raise ProviderError(
            str(result.get("error") or "unfinished handoff governance failed"),
            kind="unrecoverable",
        )
    return result


def build_provider_manifest(packet: dict[str, Any]) -> dict[str, Any]:
    """Project one prepared packet into the restricted provider contract."""

    semantic = packet.get("semantic_evidence")
    semantic_dict = semantic if isinstance(semantic, dict) else {}
    return {
        "contract_version": "autonomous-distill-manifest-v1",
        "coverage": "complete_indexed_semantic_projection",
        "project_name": packet.get("project_name"),
        "session_id": packet.get("session_id"),
        "distill_job_id": packet.get("distill_job_id"),
        "source_revision": packet.get("source_revision"),
        "expected_chunk_count": packet.get("expected_chunk_count"),
        "completed_chunk_count": packet.get("completed_chunk_count"),
        "semantic_projection": {
            key: semantic_dict.get(key)
            for key in (
                "projection",
                "exchange_count",
                "risk_exchange_count",
                "content_sha256",
                "source_revision",
                "chunks",
            )
        },
        "semantic_decision_exchanges": packet.get("semantic_decision_exchanges", []),
        "zero_candidate_exchange_refs": packet.get("zero_candidate_exchange_refs", []),
        "zero_candidate_challenge_template": packet.get(
            "zero_candidate_challenge_template"
        ),
        "response_budget": packet.get("response_budget"),
    }


def _normalize_zero_candidate_signal_labels(
    decision: Any,
    *,
    packet: dict[str, Any],
) -> Any:
    """Repair exact signal labels without inventing semantic justification.

    The provider can explain a downgrade in natural language yet omit the
    runtime's machine-readable signal key.  Finalization intentionally rejects
    that shape.  When the provider already supplied a substantive session-only
    rationale, append only the missing exact labels so the trusted gate can
    correlate the explanation with the detected signals.
    """

    if decision.candidates:
        return decision
    challenge = decision.semantic_review.zero_candidate_challenge
    template = packet.get("zero_candidate_challenge_template")
    if challenge is None or not isinstance(template, dict):
        return decision
    if challenge.future_utility != "session_only":
        return decision
    template_checks = template.get("checks")
    if not isinstance(template_checks, dict):
        return decision
    challenge_checks = challenge.checks.model_dump()
    downgraded = sorted(
        signal
        for signal, expected in template_checks.items()
        if expected == "candidate_required"
        and challenge_checks.get(signal) == "not_durable"
    )
    rationale = challenge.rationale
    missing = [signal for signal in downgraded if signal.lower() not in rationale.lower()]
    rationale_without_labels = rationale.lower()
    for signal in downgraded:
        rationale_without_labels = rationale_without_labels.replace(signal.lower(), "")
    if not missing or sum(char.isalnum() for char in rationale_without_labels) < 12:
        return decision
    updated_challenge = challenge.model_copy(
        update={
            "rationale": (
                rationale.rstrip() + " Reviewed downgraded signals: " + ", ".join(missing) + "."
            )[:4000]
        }
    )
    updated_review = decision.semantic_review.model_copy(
        update={"zero_candidate_challenge": updated_challenge}
    )
    return decision.model_copy(update={"semantic_review": updated_review})


def _zero_candidate_validation_errors(
    decision: Any,
    *,
    packet: dict[str, Any],
) -> list[str]:
    """Validate provider no-candidate state before governance/finalization."""

    if decision.candidates:
        return []
    challenge = decision.semantic_review.zero_candidate_challenge
    if challenge is None:
        return ["zero_candidate_challenge is required"]
    errors: list[str] = []
    try:
        RuntimeZeroCandidateChallenge.model_validate(
            challenge.model_dump(mode="json")
        )
    except ValueError as exc:
        errors.append(f"zero_candidate_challenge schema inconsistent: {exc}")
    template = packet.get("zero_candidate_challenge_template")
    template_checks = template.get("checks") if isinstance(template, dict) else None
    if isinstance(template_checks, dict):
        challenge_checks = challenge.checks.model_dump()
        incorrectly_absent = sorted(
            signal
            for signal, expected in template_checks.items()
            if expected == "candidate_required"
            and challenge_checks.get(signal) == "absent"
        )
        if incorrectly_absent:
            errors.append(
                "detected durable signals cannot be marked absent: "
                + ", ".join(incorrectly_absent)
            )
    return errors


def _decide_with_candidate_retry(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    packet: dict[str, Any],
    job: SessionDistillJob,
    runtime_dir: Path,
    heartbeat: Any,
) -> tuple[ProviderResult, Any, list[tuple[Any, dict[str, Any]]], list[str]]:
    """Retry once when every returned candidate violates its kind contract."""

    results: list[ProviderResult] = []
    current_manifest = manifest
    for attempt in range(2):
        result = provider.decide(
            current_manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )
        results.append(result)
        decision = _normalize_zero_candidate_signal_labels(
            result.decision,
            packet=packet,
        )
        decision = normalize_provider_review_state(decision)
        validated: list[tuple[Any, dict[str, Any]]] = []
        warnings = _zero_candidate_validation_errors(decision, packet=packet)
        for index, candidate in enumerate(decision.candidates):
            control_reason = provider_candidate_control_reason(
                candidate,
                decision=decision,
            )
            if control_reason is not None:
                warnings.append(f"candidate[{index}]: {control_reason}")
                continue
            try:
                arguments = _candidate_arguments(candidate, job=job, packet=packet)
            except ValueError as exc:
                warnings.append(f"candidate[{index}]: {exc}")
                continue
            validated.append((candidate, arguments))
        decision_valid = bool(decision.candidates or not warnings)
        if (decision_valid and (not decision.candidates or validated)) or attempt == 1:
            return _combine_provider_results(results), decision, validated, warnings
        current_manifest = {
            **manifest,
            "candidate_validation_feedback": {
                "errors": warnings,
                "instruction": (
                    "Return a corrected decision. Candidate rows must satisfy their "
                    "kind contract. For zero candidates, the challenge must satisfy "
                    "its schema and may not mark template-detected candidate_required "
                    "signals absent; create a scoped candidate/handoff or justify a "
                    "session-only not_durable downgrade."
                ),
            },
        }
    raise AssertionError("candidate retry loop did not return")


def _combine_provider_results(results: list[ProviderResult]) -> ProviderResult:
    """Preserve the final decision while accounting for every provider attempt."""

    last = results[-1]
    if len(results) == 1:
        return last

    def summed(name: str) -> int | None:
        values = [getattr(item, name) for item in results]
        return None if all(value is None for value in values) else sum(value or 0 for value in values)

    return ProviderResult(
        decision=last.decision,
        provider=last.provider,
        model=last.model,
        duration_seconds=sum(item.duration_seconds for item in results),
        input_sha256=hashlib.sha256(
            "|".join(item.input_sha256 for item in results).encode("utf-8")
        ).hexdigest(),
        response_sha256=hashlib.sha256(
            "|".join(item.response_sha256 for item in results).encode("utf-8")
        ).hexdigest(),
        input_tokens=summed("input_tokens"),
        output_tokens=summed("output_tokens"),
        total_tokens=summed("total_tokens"),
        event_count=sum(item.event_count for item in results),
        attempt_count=len(results),
        schema_valid=all(item.schema_valid for item in results),
        sandbox=last.sandbox,
        ephemeral=all(item.ephemeral for item in results),
        cwd_isolated=all(item.cwd_isolated for item in results),
        hooks_disabled=all(item.hooks_disabled for item in results),
        plugins_disabled=all(item.plugins_disabled for item in results),
        mcp_disabled=all(item.mcp_disabled for item in results),
        rules_ignored=all(item.rules_ignored for item in results),
        config_isolated=all(item.config_isolated for item in results),
    )


def normalize_provider_review_state(decision: Any) -> Any:
    """Enforce review-state invariants at the trusted runtime boundary."""

    review = decision.semantic_review
    unfinished = [str(item).strip() for item in review.unfinished_work if str(item).strip()]
    if (
        not unfinished
        or review.evidence_status == "contradicted"
        or review.promotion_decision == "blocked"
    ):
        return decision
    updates: dict[str, Any] = {}
    if review.last_turn_status != "unfinished":
        updates["last_turn_status"] = "unfinished"
    if review.evidence_status != "partial":
        updates["evidence_status"] = "partial"
    if review.promotion_decision != "partial":
        updates["promotion_decision"] = "partial"
    if not updates:
        return decision
    return decision.model_copy(
        update={"semantic_review": review.model_copy(update=updates)}
    )


def _candidate_arguments(
    candidate: Any,
    *,
    job: SessionDistillJob,
    packet: dict[str, Any],
) -> dict[str, Any]:
    evidence = _safe_evidence(candidate, packet=packet)
    common = {
        "kind": candidate.kind,
        "project_name": job.project_name,
        "distill_job_id": job.id,
        **evidence,
    }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "memory":
        _require_candidate_fields(candidate, "category", "content", "confidence")
        return {
            **common,
            "category": str(candidate.category),
            "content": str(candidate.content),
            "source": f"distill-job:{job.id}",
            "confidence": _required_confidence(candidate),
            "tags": candidate.tags or [],
        }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "rule":
        pattern = candidate.pattern or candidate.content
        if not pattern or not candidate.trigger:
            raise ValueError("rule candidate missing fields: ['pattern', 'trigger']")
        return {
            **common,
            "session_id": job.session_id,
            "pattern": str(pattern),
            "trigger": str(candidate.trigger),
            "examples": candidate.examples or [],
        }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "relation":
        _require_candidate_fields(
            candidate,
            "source_entity",
            "target_entity",
            "relation_type",
            "evidence",
            "confidence",
        )
        return {
            **common,
            "source_entity": str(candidate.source_entity),
            "target_entity": str(candidate.target_entity),
            "relation_type": str(candidate.relation_type),
            "evidence": str(candidate.evidence),
            "source": f"distill-job:{job.id}",
            "confidence": _required_confidence(candidate),
        }
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def provider_candidate_control_reason(
    candidate: Any,
    *,
    decision: Any,
) -> str | None:
    """Reject provider rows that belong to summary or handoff control state."""

    fields = (
        getattr(candidate, "category", None),
        getattr(candidate, "content", None),
        getattr(candidate, "pattern", None),
        getattr(candidate, "evidence", None),
        " ".join(getattr(candidate, "tags", None) or []),
    )
    text = " ".join(str(value or "") for value in fields).lower()
    review = decision.semantic_review
    if review.unfinished_work and any(
        marker in text
        for marker in (
            "unfinished_handoff",
            "unfinished handoff",
            "remains unfinished",
            "next task",
            "待办",
            "未完成",
            "交接",
        )
    ):
        return "unfinished work belongs to the job-bound handoff"
    historical_markers = ("superseded", "was replaced", "outdated", "已取代", "被替代")
    replacement_markers = (
        "current replacement",
        "replace with",
        "now use",
        "new default",
        "改为",
        "当前采用",
    )
    if any(marker in text for marker in historical_markers) and not any(
        marker in text for marker in replacement_markers
    ):
        return "bare superseded history belongs to summary or final outcome"
    return None


def _require_candidate_fields(candidate: DistillCandidate, *names: str) -> None:
    missing = [name for name in names if getattr(candidate, name) in {None, ""}]
    if missing:
        raise ValueError(f"{candidate.kind} candidate missing fields: {missing}")


def _required_confidence(candidate: DistillCandidate) -> float:
    if candidate.confidence is None:
        raise ValueError(f"{candidate.kind} candidate missing fields: ['confidence']")
    return float(candidate.confidence)


def _safe_evidence(candidate: Any, *, packet: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        (int(item.get("exchange_index") or 0), str(item.get("content_sha256") or ""))
        for item in packet.get("zero_candidate_exchange_refs", [])
        if isinstance(item, dict)
    }
    refs = [
        item.model_dump(mode="json", exclude_none=True)
        for item in candidate.verification_refs
    ]
    reasons = list(candidate.verification_reason_codes)
    verified_user_statement = (
        candidate.evidence_basis == "user_statement"
        and candidate.verification_outcome == "verified"
        and bool(refs)
        and all(
            ref.get("kind") == "user_statement"
            and ref.get("role") == "user"
            and (
                int(ref.get("exchange_index") or 0),
                str(ref.get("content_sha256") or ""),
            )
            in allowed
            for ref in refs
        )
    )
    if verified_user_statement:
        return {
            "evidence_basis": "user_statement",
            "verification_outcome": "verified",
            "verification_refs": refs,
            "verification_reason_codes": reasons,
        }
    reasons.append(f"autonomous_provider_cannot_verify_{candidate.evidence_basis}")
    return {
        "evidence_basis": candidate.evidence_basis,
        "verification_outcome": "unverified",
        "verification_refs": refs,
        "verification_reason_codes": list(dict.fromkeys(reasons)),
    }


def _materialize_note(job: SessionDistillJob, *, notes_dir: Path) -> dict[str, Any]:
    if not str(job.session_id).strip():
        raise ProviderError(
            "completed job has no pre-cleanup session identity for Note materialization",
            kind="unrecoverable",
        )
    return materialize_session_note(job, notes_dir=notes_dir)


def _identity_digest(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _repair_missing_notes(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path,
    notes_dir: Path,
) -> None:
    completed = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        status="completed",
        limit=200,
    )
    for job in completed:
        path, _recovered_session_id = existing_session_note_path(notes_dir, job)
        summary = str(job.semantic_review.get("session_summary") or "").strip()
        if not is_meaningful_session_summary(summary) and path is not None and path.is_file():
            recovered = _summary_from_note(path)
            if recovered:
                job = backend.transcript_store.backfill_distill_session_summary(
                    job.id,
                    session_summary=recovered,
                )
        if (
            not is_meaningful_session_summary(
                job.semantic_review.get("session_summary")
            )
            and path is None
            and job.semantic_review.get("evidence_state") == "source_pruned"
        ):
            job = backend.transcript_store.mark_distill_historical_summary_unavailable(
                job.id,
                reason="immutable_note_missing_after_source_pruned",
            )
        if (path is not None and path.is_file()) or not job.semantic_review:
            continue
        if not str(job.session_id).strip():
            # The cleanup ledger no longer has enough identity to create a new
            # immutable path; report the gap instead of inventing one.
            continue
        note = _materialize_note(job, notes_dir=notes_dir)
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={
                "last_note_materialized_at": note["materialized_at"],
                "note": note,
                "job_id": job.id,
                "session_id": job.session_id,
            },
        )


def _summary_from_note(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for heading in ("## 会话主题", "## Scope"):
        marker = content.find(heading)
        if marker < 0:
            continue
        body = content[marker + len(heading) :]
        next_heading = body.find("\n## ")
        if next_heading >= 0:
            body = body[:next_heading]
        compact = " ".join(line.strip() for line in body.splitlines() if line.strip())
        if len(compact) >= 12:
            return compact[:2000]
    return None


def _record_success_receipt(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None,
    client: str,
    job: SessionDistillJob,
    note: dict[str, Any],
    provider_receipt: dict[str, Any] | None,
) -> dict[str, str | None]:
    completed_at = job.completed_at.isoformat() if job.completed_at else _now()
    semantic_success_at = _now() if provider_receipt is not None else None
    completion = {
        "last_semantic_success_at": semantic_success_at,
        "last_job_completed_at": completed_at,
        "last_note_materialized_at": str(note["materialized_at"]),
    }
    current = (
        read_autonomous_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
        )
        or {}
    )
    verified_completion = {
        "schema_version": 1,
        "trigger_id": trigger_id,
        "client": client,
        "execution_source": "autonomous_worker",
        "hook_launch_verified": current.get("hook_launch_verified") is True,
        "hook_config_fingerprint": current.get("hook_config_fingerprint"),
        "runtime_fingerprint": current.get("runtime_fingerprint"),
        "config_fingerprint": current.get("config_fingerprint"),
        "hook_reentry_count": int(current.get("hook_reentry_count") or 0),
        "job_id": job.id,
        "session_id": job.session_id,
        **completion,
        "provider": provider_receipt,
        "note": note,
    }
    _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=project_root,
        update={
            "state": "succeeded",
            "trigger_id": trigger_id,
            "client": client,
            "execution_source": "autonomous_worker",
            "job_id": job.id,
            "session_id": job.session_id,
            **completion,
            "provider": provider_receipt,
            "note": note,
            "last_verified_completion": verified_completion,
            "error": None,
        },
    )
    return completion


__all__ = [
    "build_provider_manifest",
    "autonomous_config_fingerprint",
    "autonomous_receipt_path",
    "autonomous_runtime_fingerprint",
    "read_autonomous_receipt",
    "provider_candidate_control_reason",
    "normalize_provider_review_state",
    "run_autonomous_distill_batch",
]
