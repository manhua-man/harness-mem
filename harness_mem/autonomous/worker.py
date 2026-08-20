"""Durable autonomous distill runner used by detached host workers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterator, Protocol
from uuid import uuid4

from harness_mem.autonomous.models import (
    AssimilationDecision,
    CandidateVerificationDecision,
    DistillCandidate,
    validate_atomic_knowledge_statement,
)
from harness_mem.autonomous.provider import (
    CodexExecProvider,
    ProviderError,
    ProviderResult,
    ResponsesApiProvider,
)
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    create_separated_candidates,
    normalize_identical_truth_mutations,
    prepare_separated_assimilation,
    validate_separated_assimilation_decision,
)
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
_MAX_ASSIMILATION_CANDIDATES_PER_CALL = 1
_RUNTIME_SOURCE_FILES = (
    Path(__file__),
    Path(__file__).with_name("models.py"),
    Path(__file__).with_name("provider.py"),
    Path(__file__).parents[1] / "host_entry" / "__main__.py",
    Path(__file__).parents[1] / "hook_background.py",
    Path(__file__).parents[1] / "commands" / "maintenance.py",
    Path(__file__).parents[1] / "commands" / "distill_lifecycle.py",
    Path(__file__).parents[1] / "commands" / "separated_assimilation.py",
    Path(__file__).parents[1] / "commands" / "knowledge_assimilation.py",
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

    def assimilate(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Any = None,
    ) -> ProviderResult: ...


def _provider_call_with_transport_fallback(
    provider: DistillProvider,
    method_name: str,
    manifest: dict[str, Any],
    *,
    runtime_dir: Path,
    heartbeat: Any,
) -> ProviderResult:
    """Recover a narrow Responses EOF through the isolated Codex transport."""

    method = getattr(provider, method_name)
    started = time.monotonic()
    try:
        return method(
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )
    except ProviderError as primary_error:
        if getattr(provider, "name", "") == "responses_api" and primary_error.kind == "setup_required":
            selected_model = (
                getattr(provider, "assimilation_model", None)
                if method_name == "assimilate"
                else getattr(provider, "model", None)
            )
            fallback = CodexExecProvider(
                model=str(selected_model or "").strip() or None,
                timeout_seconds=300,
            )
            if not fallback.executable:
                raise
            fallback_method = getattr(fallback, method_name)
            try:
                recovered = fallback_method(
                    manifest,
                    runtime_dir=runtime_dir,
                    heartbeat=heartbeat,
                )
            except ProviderError as fallback_error:
                raise ProviderError(
                    f"{primary_error}; codex_exec fallback failed: {fallback_error}",
                    kind=(
                        "transient"
                        if fallback_error.kind == "setup_required"
                        else fallback_error.kind
                    ),
                    exit_code=fallback_error.exit_code,
                ) from fallback_error
            return ProviderResult(
                decision=recovered.decision,
                provider=f"responses_api->{recovered.provider}",
                model=recovered.model,
                duration_seconds=time.monotonic() - started,
                input_sha256=recovered.input_sha256,
                response_sha256=recovered.response_sha256,
                input_tokens=recovered.input_tokens,
                output_tokens=recovered.output_tokens,
                total_tokens=recovered.total_tokens,
                event_count=recovered.event_count,
                attempt_count=recovered.attempt_count + 1,
                schema_valid=recovered.schema_valid,
                sandbox=recovered.sandbox,
                ephemeral=recovered.ephemeral,
                cwd_isolated=recovered.cwd_isolated,
                hooks_disabled=recovered.hooks_disabled,
                plugins_disabled=recovered.plugins_disabled,
                mcp_disabled=recovered.mcp_disabled,
                rules_ignored=recovered.rules_ignored,
                config_isolated=recovered.config_isolated,
            )
        if (
            getattr(provider, "name", "") != "responses_api"
            or primary_error.kind != "transient"
            or "unexpected eof" not in str(primary_error).casefold()
        ):
            raise
        selected_model = (
            getattr(provider, "assimilation_model", None)
            if method_name == "assimilate"
            else getattr(provider, "model", None)
        )
        fallback = CodexExecProvider(
            model=str(selected_model or "").strip() or None,
            timeout_seconds=300,
        )
        if not fallback.executable:
            raise
        fallback_method = getattr(fallback, method_name)
        try:
            recovered = fallback_method(
                manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        except ProviderError as fallback_error:
            raise ProviderError(
                f"{primary_error}; codex_exec fallback failed: {fallback_error}",
                kind=(
                    "transient"
                    if fallback_error.kind == "setup_required"
                    else fallback_error.kind
                ),
                exit_code=fallback_error.exit_code,
            ) from fallback_error
        return ProviderResult(
            decision=recovered.decision,
            provider=f"responses_api->{recovered.provider}",
            model=recovered.model,
            duration_seconds=time.monotonic() - started,
            input_sha256=recovered.input_sha256,
            response_sha256=recovered.response_sha256,
            input_tokens=recovered.input_tokens,
            output_tokens=recovered.output_tokens,
            total_tokens=recovered.total_tokens,
            event_count=recovered.event_count,
            attempt_count=recovered.attempt_count + 1,
            schema_valid=recovered.schema_valid,
            sandbox=recovered.sandbox,
            ephemeral=recovered.ephemeral,
            cwd_isolated=recovered.cwd_isolated,
            hooks_disabled=recovered.hooks_disabled,
            plugins_disabled=recovered.plugins_disabled,
            mcp_disabled=recovered.mcp_disabled,
            rules_ignored=recovered.rules_ignored,
            config_isolated=recovered.config_isolated,
        )

    def verify(
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
        "dispatch_generation": receipt.get("dispatch_generation"),
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
    dispatch_generation: str | None = None,
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
            "dispatch_generation": dispatch_generation,
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
    batch_state = (
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
    preferred_outcome = next(
        (item for item in outcomes if item.get("job_id") == preferred_job_id),
        None,
    )
    if preferred_job_id is not None:
        preferred_status = (
            str(preferred_outcome.get("status") or "deferred")
            if preferred_outcome is not None
            else "deferred"
        )
        state = {
            "completed": "succeeded",
            "deferred": "deferred",
            "busy": "busy",
        }.get(preferred_status, "deferred")
        latest_evidence = (
            preferred_outcome if preferred_status == "completed" else None
        )
        receipt_error = (
            None
            if preferred_status == "completed"
            else (preferred_outcome or {}).get("error")
            or {
                "kind": "preferred_job_not_completed",
                "message": "the trigger-bound distill job did not complete",
            }
        )
    else:
        state = batch_state
        receipt_error = None if latest_success else latest_error
    receipt = _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": state,
            "finished_at": _now(),
            "trigger_id": trigger_id,
            "batch": {
                "state": batch_state,
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
            "error": receipt_error,
            "last_batch_error": (
                receipt_error if preferred_job_id is not None else latest_error
            ),
            "last_background_error": (
                latest_error if preferred_job_id is not None else None
            ),
        },
    )
    return {
        "success": bool(succeeded) or not outcomes,
        "state": batch_state,
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
        and job.status in {"queued", "parked", "processing", "reviewing", "retryable"}
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
        verification_result: ProviderResult | None = None
        if validated_candidates:
            verify = getattr(provider, "verify", None)
            if not callable(verify):
                raise ProviderError(
                    "autonomous provider does not implement per-point semantic verification",
                    kind="setup_required",
                )
            verification_result, validated_candidates = _verify_candidates(
                provider,
                manifest=_build_candidate_verification_manifest(
                    packet=packet,
                    validated_candidates=validated_candidates,
                    project_root=project_root,
                ),
                validated_candidates=validated_candidates,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        # Persist only the trusted per-point verification result.  The
        # extraction model's requested verification_outcome is an input claim,
        # not evidence that may reach assimilation.
        governed_candidate_ids = asyncio.run(
            create_separated_candidates(
                backend,
                project_name=project_name,
                distill_job_id=job.id,
                candidate_arguments=[
                    arguments for _candidate, arguments in validated_candidates
                ],
            )
        )
        governed_count = len(governed_candidate_ids)
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
        review_payload = decision.semantic_review.model_dump(
            mode="json", exclude_none=True
        )
        assimilation_result: ProviderResult | None = None
        if governed_candidate_ids:
            prepared = asyncio.run(
                prepare_separated_assimilation(
                    backend,
                    project_name=project_name,
                    project_root=str(project_root),
                    candidate_ids=governed_candidate_ids,
                )
            )
            if prepared.eligible_candidate_ids:
                assimilate = getattr(provider, "assimilate", None)
                if not callable(assimilate):
                    raise ProviderError(
                        "autonomous provider does not implement post-verification assimilation",
                        kind="setup_required",
                    )
                assimilation_result = _assimilate_prepared_in_bounded_batches(
                    provider,
                    prepared=prepared,
                    runtime_dir=runtime_dir,
                    heartbeat=heartbeat,
                )
                if not isinstance(assimilation_result.decision, AssimilationDecision):
                    raise ProviderError(
                        "assimilation provider returned an unexpected decision type",
                        kind="unrecoverable",
                    )
                assimilation = validate_separated_assimilation_decision(
                    prepared,
                    assimilation_result.decision,
                )
            else:
                assimilation = validate_separated_assimilation_decision(
                    prepared,
                    AssimilationDecision(points=[]),
                )
            review_payload["assimilation"] = assimilation
        finalized = tools.tool_finalize_session_distill(
            project_name=project_name,
            job_id=job_id,
            semantic_review=review_payload,
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
        if verification_result is not None:
            provider_receipt["extraction"] = provider_result.receipt()
            provider_receipt["verification"] = verification_result.receipt()
        if assimilation_result is not None:
            provider_receipt["assimilation"] = assimilation_result.receipt()
            provider_receipt["combined"] = {
                "input_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.input_tokens,
                        verification_result.input_tokens if verification_result else None,
                    ),
                    assimilation_result.input_tokens,
                ),
                "output_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.output_tokens,
                        verification_result.output_tokens if verification_result else None,
                    ),
                    assimilation_result.output_tokens,
                ),
                "total_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.total_tokens,
                        verification_result.total_tokens if verification_result else None,
                    ),
                    assimilation_result.total_tokens,
                ),
                "duration_seconds": round(
                    provider_result.duration_seconds
                    + (verification_result.duration_seconds if verification_result else 0.0)
                    + assimilation_result.duration_seconds,
                    3,
                ),
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
        str(item).strip() for item in review.unfinished_work if str(item).strip()
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
    missing = [
        signal for signal in downgraded if signal.lower() not in rationale.lower()
    ]
    rationale_without_labels = rationale.lower()
    for signal in downgraded:
        rationale_without_labels = rationale_without_labels.replace(signal.lower(), "")
    if not missing or sum(char.isalnum() for char in rationale_without_labels) < 12:
        return decision
    updated_challenge = challenge.model_copy(
        update={
            "rationale": (
                rationale.rstrip()
                + " Reviewed downgraded signals: "
                + ", ".join(missing)
                + "."
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
        RuntimeZeroCandidateChallenge.model_validate(challenge.model_dump(mode="json"))
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
        result = _provider_call_with_transport_fallback(
            provider,
            "decide",
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
        if decision_valid and (not decision.candidates or validated):
            return _combine_provider_results(results), decision, validated, warnings
        if attempt == 1:
            raise ProviderError(
                "provider correction failed candidate/zero-candidate validation: "
                + "; ".join(warnings)[:2000],
                kind="unrecoverable",
            )
        current_manifest = {
            **manifest,
            "candidate_validation_feedback": {
                "errors": warnings,
                "instruction": (
                    "Return a corrected decision. Candidate rows must satisfy their "
                    "kind contract. For zero candidates, the challenge must satisfy "
                    "its schema and may not mark template-detected candidate_required "
                    "signals absent. A no_durable_candidate result requires "
                    "evidence_fidelity=complete and promotion_decision=no_promotion. "
                    "If evidence is partial/contradicted or a signal remains candidate_required, "
                    "create a scoped defer candidate or handoff instead of returning zero candidates."
                ),
            },
        }
    raise AssertionError("candidate retry loop did not return")


def _assimilate_with_schema_retry(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    runtime_dir: Path,
    heartbeat: Any,
    validate_decision: Callable[[AssimilationDecision], Any] | None = None,
) -> ProviderResult:
    """Give a malformed post-verification response two bounded correction passes.

    Candidate extraction already has a field-contract retry.  Atomic
    ``knowledge_items`` introduced another strict structured shape, so the
    second semantic call needs the same bounded recovery: an omitted item title,
    unavailable target, or invalid target cardinality must not strand a complete
    session in ``reviewing``. Each retry passes the validator's exact feedback and
    still fails closed after two corrections.
    """

    current_manifest = manifest
    for attempt in range(3):
        try:
            result = _provider_call_with_transport_fallback(
                provider,
                "assimilate",
                current_manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        except ProviderError as exc:
            invalid_shape = "invalid assimilation json" in str(exc).lower()
            if attempt < 2 and exc.kind == "unrecoverable" and invalid_shape:
                current_manifest = {
                    **manifest,
                    "assimilation_validation_feedback": {
                        "errors": [str(exc)[:2000]],
                        "instruction": (
                            "Return a corrected assimilation decision. A knowledge_items "
                            "row must contain title, statement, topic_path, and claim_kind; "
                            "use canonical_title/canonical_statement instead when writing "
                            "one item. When knowledge_items is non-empty, leave point-level "
                            "canonical_title and canonical_statement null and topic_path empty. "
                            "Never keep an umbrella item together with narrower items that split "
                            "the same requirement. If a requirement offers alternative enforcement "
                            "mechanisms, preserve the either/or in one atomic sentence with one "
                            "modal instead of expanding it into separate must clauses. Return every "
                            "supplied candidate_id at least once. A broad candidate can "
                            "return multiple points with distinct dispositions and targets. "
                            "Preserve every technical identifier "
                            "named in the candidate; when feedback lists dropped terms, copy those "
                            "identifiers exactly into the corrected knowledge statement. Set "
                            "matched_truth_handles=[] for add, no_write, handoff, defer, and "
                            "reject; use exactly one available handle for confirm, refine, or "
                            "supersede. If an error says independent obligations or separate "
                            "steps, split the offending statement into distinct atomic "
                            "knowledge_items within the three-item limit. Do not repeat or "
                            "lightly rephrase the invalid combined statement; if it cannot "
                            "be split within the bound, retain only the highest-value atomic "
                            "item or choose no_write. Keep a paired growth and lossless-"
                            "reconstruction qualification test contract in one testing item "
                            "rather than one item per test name."
                        ),
                    },
                }
                continue
            raise
        if isinstance(result.decision, AssimilationDecision):
            if validate_decision is not None:
                try:
                    validate_decision(result.decision)
                except ValueError as exc:
                    if attempt < 2:
                        current_manifest = {
                            **manifest,
                            "assimilation_validation_feedback": {
                                "errors": [str(exc)[:2000]],
                                "instruction": (
                                    "Return every supplied candidate_id at least once in a "
                                    "corrected assimilation decision; a broad candidate may "
                                    "emit multiple points with distinct dispositions and targets. "
                                    "Set matched_truth_handles=[] "
                                    "for add, no_write, handoff, defer, and reject. A confirm, "
                                    "refine, or supersede point needs exactly one supplied truth "
                                    "handle; do not reference unavailable handles. For confirm, "
                                    "no_write, handoff, defer, conflict, and reject, return no "
                                    "knowledge_items and leave canonical_title, "
                                    "canonical_statement, and topic_path empty. Correct every named "
                                    "error before returning. Never keep an umbrella item together "
                                    "with narrower items that split the same requirement. Preserve "
                                    "alternative enforcement mechanisms as one either/or sentence "
                                    "with one modal. Preserve every candidate technical identifier "
                                    "exactly, including any terms named as dropped in the error. "
                                    "Keep a paired growth and lossless-reconstruction qualification "
                                    "test contract in one testing item rather than one item per test."
                                ),
                            },
                        }
                        continue
                    repaired = _repair_invalid_writing_with_source_clauses(
                        result.decision,
                        manifest=manifest,
                        error=exc,
                    )
                    if repaired is not None:
                        try:
                            validate_decision(repaired)
                        except ValueError:
                            pass
                        else:
                            return replace(
                                result,
                                decision=repaired,
                                provider=f"{result.provider}->runtime_source_clause",
                            )
                    raise ProviderError(
                        f"invalid assimilation decision: {exc}",
                        kind="unrecoverable",
                    ) from exc
            return result
        raise ProviderError(
            "assimilation provider returned an unexpected decision type",
            kind="unrecoverable",
        )
    raise AssertionError("assimilation retry loop did not return")


def _repair_invalid_writing_with_source_clauses(
    decision: AssimilationDecision,
    *,
    manifest: dict[str, Any],
    error: ValueError,
) -> AssimilationDecision | None:
    """Recover verified atomic source clauses after repeated lossy wording.

    This does not synthesize missing facts. It copies only clauses from the
    already verified candidate, and only when every clause is independently
    atomic. Conditional alternatives and broad/ambiguous candidates still fail
    closed and are deferred by the caller.
    """

    message = str(error)
    wording_error_markers = (
        "canonical knowledge",
        "knowledge item",
        "knowledge_items",
    )
    if not any(marker in message for marker in wording_error_markers):
        return None
    if len(decision.points) != 1:
        return None
    projections = [
        item
        for item in manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    ]
    if len(projections) != 1:
        return None
    projection = projections[0]
    point = decision.points[0]
    if point.candidate_id != str(projection.get("candidate_id") or ""):
        return None
    if point.disposition not in {"add", "refine", "supersede"}:
        return None
    if point.knowledge_items and len(point.knowledge_items) > 3:
        return None

    source = str(projection.get("statement") or "").strip()
    if not source or re.search(r"(?:；|;)\s*(?:如果|否则|if\b|otherwise\b)", source, re.I):
        return None
    source_clauses = _split_verified_source_clauses(source)
    if not 1 <= len(source_clauses) <= 3:
        return None
    if _source_clauses_have_overlapping_identifiers(source_clauses):
        return None
    atomic_clauses: list[str] = []
    for clause in source_clauses:
        try:
            atomic_clauses.append(validate_atomic_knowledge_statement(clause))
        except ValueError:
            return None
    if point.disposition == "refine" and len(atomic_clauses) != 1:
        return None

    payload = decision.model_dump(mode="json")
    raw_point = payload["points"][0]
    if raw_point.get("knowledge_items"):
        existing_items = raw_point["knowledge_items"]
        template = existing_items[0]
        raw_point["knowledge_items"] = [
            {
                "title": (
                    str(template.get("title") or "")
                    if len(atomic_clauses) == 1
                    else _source_clause_title(clause)
                ),
                "statement": clause,
                "topic_path": list(template.get("topic_path") or []),
                "claim_kind": template.get("claim_kind"),
            }
            for clause in atomic_clauses
        ]
        if any(not item["title"] for item in raw_point["knowledge_items"]):
            return None
    elif raw_point.get("canonical_statement"):
        return None
    else:
        return None
    return AssimilationDecision.model_validate(payload)


def _source_clauses_have_overlapping_identifiers(clauses: list[str]) -> bool:
    """Keep deterministic fallback from duplicating the same technical checklist."""

    ignored = {
        "adapter",
        "candidate",
        "chunk",
        "current",
        "knowledge",
        "must",
        "revision",
        "session",
        "should",
        "support",
        "test",
    }
    identifiers = [
        {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", clause)
            if token.casefold() not in ignored
        }
        for clause in clauses
    ]
    return any(
        len(left & right) >= 2
        for index, left in enumerate(identifiers)
        for right in identifiers[index + 1 :]
    )


def _split_verified_source_clauses(source: str) -> list[str]:
    """Split only explicit source conjunctions while retaining their shared subject."""

    clauses = [
        clause.strip(" \t\r\n,，。")
        for clause in source.replace("；", ";").split(";")
        if clause.strip(" \t\r\n,，。")
    ]
    expanded: list[str] = []
    for clause in clauses:
        modal = re.match(r"^(?P<prefix>.+?(?:必须|应当|应该|应|须))(?P<body>.+)$", clause)
        if modal is None:
            expanded.append(clause)
            continue
        prefix = modal.group("prefix")
        body = modal.group("body")
        split = re.split(
            r"，并(?=(?:通过|具备|声明|完成|提供|执行|保存|记录))",
            body,
            maxsplit=1,
        )
        if len(split) == 2:
            expanded.extend([prefix + split[0], prefix + split[1]])
        else:
            expanded.append(clause)

    atomic_candidates: list[str] = []
    for clause in expanded:
        if not (
            re.search(r"(?:路径|样本|匹配规则)", clause)
            and re.search(r"hook\s*/\s*transcript|hook.+transcript", clause, re.I)
        ):
            atomic_candidates.append(clause)
            continue
        modal = re.match(
            r"^(?P<prefix>.+?(?:必须|应当|应该|应|须)(?:声明|具备)?)(?P<body>.+)$",
            clause,
        )
        if modal is None:
            atomic_candidates.append(clause)
            continue
        body = modal.group("body")
        capability = re.search(
            r"(?:、|，|和|及)\s*(?P<capability>hook\s*/\s*transcript\s*能力.*)$",
            body,
            re.I,
        )
        if capability is None:
            atomic_candidates.append(clause)
            continue
        left = body[: capability.start()].strip(" 、,，")
        if not left:
            atomic_candidates.append(clause)
            continue
        atomic_candidates.extend(
            [modal.group("prefix") + left, modal.group("prefix") + capability.group("capability")]
        )
    return [clause.strip(" \t\r\n,，。") for clause in atomic_candidates if clause.strip()]


def _source_clause_title(source_clause: str) -> str:
    """Derive a bounded title from one copied source clause, without new facts."""

    normalized = " ".join(source_clause.split()).strip(" ,，。")
    match = re.search(r"(?:必须|应当|应该|应|须)", normalized)
    if match is None:
        head = re.split(r"[、,，。]", normalized, maxsplit=1)[0]
        return head[:80] or "Verified source constraint"
    subject = normalized[: match.start()].strip()
    subject = re.sub(r"^(?:每个|每一|所有)\s*", "", subject).strip()
    predicate = normalized[match.end() :].strip()
    predicate = re.split(r"[、,，。]", predicate, maxsplit=1)[0].strip()
    title = " ".join(part for part in (subject, predicate) if part).strip()
    return title[:80] or "Verified source constraint"


def _assimilate_prepared_in_bounded_batches(
    provider: DistillProvider,
    *,
    prepared: SeparatedPreparedAssimilation,
    runtime_dir: Path,
    heartbeat: Any,
) -> ProviderResult:
    """Bound strict output size while preserving one complete runtime decision.

    Ten independently verified points can exceed the provider's practical
    structured-output latency even though the input manifest is compact. Each
    bounded call sees the same current truth, and the trusted runtime merges the
    returned points before revalidating exact full-job coverage.
    """

    eligible = list(prepared.eligible_candidate_ids)
    if not eligible:
        raise ProviderError(
            "bounded assimilation requires at least one eligible candidate",
            kind="unrecoverable",
        )
    projected = {
        str(item.get("candidate_id") or ""): dict(item)
        for item in prepared.manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    }
    if any(candidate_id not in projected for candidate_id in eligible):
        raise ProviderError(
            "assimilation manifest is missing an eligible candidate projection",
            kind="unrecoverable",
        )

    results: list[ProviderResult] = []
    combined_points = []
    prior_batch_knowledge: list[dict[str, Any]] = []
    retired_truth_handles: set[str] = set()
    for offset in range(0, len(eligible), _MAX_ASSIMILATION_CANDIDATES_PER_CALL):
        batch_ids = tuple(
            eligible[offset : offset + _MAX_ASSIMILATION_CANDIDATES_PER_CALL]
        )
        available_truth_by_handle = {
            handle: truth_id
            for handle, truth_id in prepared.truth_by_handle.items()
            if handle not in retired_truth_handles
        }
        batch_prepared = SeparatedPreparedAssimilation(
            project_name=prepared.project_name,
            project_root=prepared.project_root,
            candidate_ids=batch_ids,
            eligible_candidate_ids=batch_ids,
            automatic_points=(),
            answer_status_by_candidate={
                candidate_id: prepared.answer_status_by_candidate[candidate_id]
                for candidate_id in batch_ids
            },
            truth_by_handle=available_truth_by_handle,
            manifest={
                **prepared.manifest,
                "verified_candidates": [projected[candidate_id] for candidate_id in batch_ids],
                "prior_batch_knowledge": list(prior_batch_knowledge),
                "current_truth": [
                    item
                    for item in prepared.manifest.get("current_truth") or []
                    if isinstance(item, dict)
                    and str(item.get("handle") or "") in available_truth_by_handle
                ],
            },
        )

        def validate_batch(candidate: AssimilationDecision) -> dict[str, Any]:
            return validate_separated_assimilation_decision(
                batch_prepared,
                candidate,
            )

        try:
            result = _assimilate_with_schema_retry(
                provider,
                manifest=batch_prepared.manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
                validate_decision=validate_batch,
            )
        except ProviderError as exc:
            if exc.kind != "unrecoverable":
                raise
            result = _deferred_assimilation_result(
                provider,
                candidate_id=batch_ids[0],
                error=exc,
                manifest=batch_prepared.manifest,
            )
        if not isinstance(result.decision, AssimilationDecision):
            raise ProviderError(
                "assimilation provider returned an unexpected decision type",
                kind="unrecoverable",
            )
        normalized_decision = normalize_identical_truth_mutations(
            batch_prepared,
            result.decision,
        )
        if normalized_decision is not result.decision:
            result = replace(result, decision=normalized_decision)
        normalized_batch = validate_separated_assimilation_decision(
            batch_prepared,
            result.decision,
        )
        results.append(result)
        combined_points.extend(result.decision.points)
        retired_truth_handles.update(
            str(handle)
            for point in result.decision.points
            if point.disposition in {"refine", "supersede"}
            for handle in point.matched_truth_handles
        )
        for point in normalized_batch["points"]:
            knowledge_items = list(point.get("knowledge_items") or [])
            if knowledge_items:
                prior_batch_knowledge.extend(
                    {
                        "candidate_id": str(point["candidate_id"]),
                        "title": str(item["title"]),
                        "statement": str(item["statement"]),
                        "topic_path": list(item["topic_path"]),
                    }
                    for item in knowledge_items
                )
            elif point.get("canonical_title") and point.get("canonical_statement"):
                prior_batch_knowledge.append(
                    {
                        "candidate_id": str(point["candidate_id"]),
                        "title": str(point["canonical_title"]),
                        "statement": str(point["canonical_statement"]),
                        "topic_path": list(point.get("topic_path") or []),
                    }
                )

    combined_decision = AssimilationDecision(points=combined_points)
    validate_separated_assimilation_decision(prepared, combined_decision)
    return _combine_provider_results(results, decision=combined_decision)


def _deferred_assimilation_result(
    provider: DistillProvider,
    *,
    candidate_id: str,
    error: ProviderError,
    manifest: dict[str, Any],
) -> ProviderResult:
    """Isolate one invalid semantic point without weakening the truth gate."""

    decision = AssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": candidate_id,
                    "disposition": "defer",
                    "matched_truth_handles": [],
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "knowledge_items": [],
                    "reason": (
                        "The bounded assimilation output remained invalid after "
                        "correction, so this point was deferred without a truth write. "
                        f"Validation error: {str(error)[:600]}"
                    ),
                }
            ]
        }
    )
    model = str(
        getattr(provider, "assimilation_model", None)
        or getattr(provider, "model", None)
        or ""
    ).strip() or None
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    return ProviderResult(
        decision=decision,
        provider=f"{getattr(provider, 'name', 'provider')}->runtime_defer",
        model=model,
        duration_seconds=0.0,
        input_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        response_sha256=hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        event_count=0,
        attempt_count=3,
        schema_valid=False,
    )


def _build_candidate_verification_manifest(
    *,
    packet: dict[str, Any],
    validated_candidates: list[tuple[Any, dict[str, Any]]],
    project_root: Path,
) -> dict[str, Any]:
    """Bind each extracted claim to the exact current text it cites."""

    windows = {
        int(item["exchange_index"]): item
        for item in packet.get("semantic_decision_exchanges") or []
        if isinstance(item, dict) and item.get("exchange_index") is not None
    }
    rows: list[dict[str, Any]] = []
    for index, (candidate, arguments) in enumerate(validated_candidates):
        sources: list[dict[str, Any]] = []
        for ref in candidate.verification_refs:
            if ref.kind == "user_statement" and ref.exchange_index in windows:
                window = windows[int(ref.exchange_index)]
                sources.append(
                    {
                        "kind": "user_statement",
                        "exchange_index": ref.exchange_index,
                        "content_sha256": ref.content_sha256,
                        "content": window.get("content"),
                    }
                )
            elif ref.kind == "repository" and ref.locator:
                locator = Path(ref.locator)
                path = (project_root / locator).resolve()
                if (
                    locator.is_absolute()
                    or not _path_is_within(path, project_root.resolve())
                    or not path.is_file()
                ):
                    sources.append(
                        {
                            "kind": "repository",
                            "locator": ref.locator,
                            "content_sha256": ref.content_sha256,
                            "content": None,
                        }
                    )
                else:
                    current_content = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    sources.append(
                        {
                            "kind": "repository",
                            "locator": ref.locator,
                            "content_sha256": ref.content_sha256,
                            "current_content_sha256": hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                            "content": current_content[:16000],
                        }
                    )
            elif ref.kind == "transcript" and ref.chunk_index is not None:
                chunks = packet.get("semantic_evidence", {}).get("chunks", [])
                chunk = next(
                    (
                        item
                        for item in chunks
                        if int(item.get("chunk_index", -1)) == ref.chunk_index
                    ),
                    None,
                )
                sources.append(
                    {
                        "kind": "transcript",
                        "chunk_index": ref.chunk_index,
                        "content_sha256": ref.content_sha256,
                        "content": chunk.get("content") if isinstance(chunk, dict) else None,
                    }
                )
        rows.append(
            {
                "candidate_index": index,
                "kind": candidate.kind,
                "statement": _candidate_statement_from_arguments(arguments),
                "sources": sources,
            }
        )
    return {
        "contract_version": "candidate-semantic-verification-v1",
        "project_name": packet.get("project_name"),
        "candidates": rows,
    }


def _candidate_statement_from_arguments(arguments: dict[str, Any]) -> str:
    kind = arguments.get("kind")
    if kind == "memory":
        return str(arguments.get("content") or "")
    if kind == "rule":
        return f"When {arguments.get('trigger')}, {arguments.get('pattern')}"
    return " ".join(
        str(arguments.get(name) or "")
        for name in ("source_entity", "relation_type", "target_entity")
    ).strip()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _verify_candidates(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    validated_candidates: list[tuple[Any, dict[str, Any]]],
    runtime_dir: Path,
    heartbeat: Any,
) -> tuple[ProviderResult, list[tuple[Any, dict[str, Any]]]]:
    result = _provider_call_with_transport_fallback(
        provider,
        "verify",
        manifest,
        runtime_dir=runtime_dir,
        heartbeat=heartbeat,
    )
    if not isinstance(result.decision, CandidateVerificationDecision):
        raise ProviderError(
            "verification provider returned an unexpected decision type",
            kind="unrecoverable",
        )
    points = list(result.decision.points)
    indexes = [point.candidate_index for point in points]
    expected = list(range(len(validated_candidates)))
    if sorted(indexes) != expected or len(indexes) != len(set(indexes)):
        raise ProviderError(
            "verification decision must cover every extracted candidate once",
            kind="unrecoverable",
        )
    by_index = {point.candidate_index: point for point in points}
    verified: list[tuple[Any, dict[str, Any]]] = []
    for index, (candidate, arguments) in enumerate(validated_candidates):
        point = by_index[index]
        updated = dict(arguments)
        codes = list(updated.get("verification_reason_codes") or [])
        if _is_unfinished_task_envelope_only(manifest, candidate_index=index):
            # A request template is evidence of what to do in that one session,
            # not evidence of a project rule.  This is intentionally a trusted
            # deterministic boundary: models previously promoted Read/Write/
            # Acceptance instructions from sessions with no assistant result.
            updated["verification_outcome"] = "not_applicable"
            codes.extend(
                ["session_only_not_durable", "unfinished_task_envelope"]
            )
        elif point.semantic_support == "supported" and point.future_scope == "durable":
            updated["verification_outcome"] = "verified"
            codes.extend(["semantic_support_verified", "future_utility_verified"])
            rebound_refs = _rebind_current_repository_refs(
                updated.get("verification_refs") or [],
                manifest=manifest,
                candidate_index=index,
            )
            if rebound_refs is not None:
                updated["verification_refs"] = rebound_refs
                codes.append("repository_ref_rebound_to_current")
        elif point.semantic_support == "contradicted":
            updated["verification_outcome"] = "contradicted"
            codes.append("semantic_support_contradicted")
        elif point.semantic_support == "supported" and point.future_scope == "session_only":
            updated["verification_outcome"] = "not_applicable"
            codes.append("session_only_not_durable")
        else:
            updated["verification_outcome"] = "unverified"
            codes.append("semantic_support_incomplete")
        updated["verification_reason_codes"] = list(dict.fromkeys(codes))
        verified.append((candidate, updated))
    return result, verified


_TASK_ENVELOPE_MARKERS = (
    "goal:",
    "working directory:",
    "read:",
    "write:",
    "acceptance:",
    "preflight:",
    "hard boundary:",
    "verification:",
    "目标：",
    "工作目录：",
    "读取：",
    "写入：",
    "验收：",
    "预检：",
    "硬边界：",
    "验证：",
)


def _is_unfinished_task_envelope_only(
    manifest: dict[str, Any], *, candidate_index: int
) -> bool:
    """Recognize a one-message task template with no recorded result.

    This is deliberately narrower than a general natural-language classifier.
    It only catches the concrete false-positive class where all evidence is a
    user task envelope and the semantic exchange has no assistant outcome.
    Explicit project decisions outside that template continue through normal
    semantic verification.
    """

    row = next(
        (
            value
            for value in manifest.get("candidates") or []
            if isinstance(value, dict)
            and int(value.get("candidate_index", -1)) == candidate_index
        ),
        None,
    )
    if not isinstance(row, dict):
        return False
    sources = row.get("sources") or []
    if not sources or any(
        not isinstance(source, dict) or source.get("kind") != "user_statement"
        for source in sources
    ):
        return False
    source_text = "\n".join(
        str(source.get("content") or "") for source in sources
    ).casefold()
    if "assistant outcome:" in source_text:
        return False
    return sum(marker in source_text for marker in _TASK_ENVELOPE_MARKERS) >= 2


def _rebind_current_repository_refs(
    refs: list[Any],
    *,
    manifest: dict[str, Any],
    candidate_index: int,
) -> list[dict[str, Any]] | None:
    """Bind semantically reverified repository refs to current file bytes.

    Historical sessions carry the digest that was current when the conversation
    happened. A changed digest alone does not prove that the claim is stale. Once
    the bounded verifier confirms that today's file still supports the claim, the
    trusted runtime replaces only the digest with the one it computed itself.
    """

    candidate_rows = manifest.get("candidates") or []
    row = next(
        (
            item
            for item in candidate_rows
            if isinstance(item, dict)
            and int(item.get("candidate_index", -1)) == candidate_index
        ),
        None,
    )
    if row is None:
        return None
    current_by_locator = {
        str(source.get("locator") or ""): str(
            source.get("current_content_sha256") or ""
        )
        for source in row.get("sources") or []
        if isinstance(source, dict)
        and source.get("kind") == "repository"
        and source.get("locator")
        and source.get("current_content_sha256")
    }
    if not current_by_locator:
        return None
    rebound: list[dict[str, Any]] = []
    changed = False
    for value in refs:
        ref = dict(value) if isinstance(value, dict) else value.model_dump(
            mode="json", exclude_none=True
        )
        locator = str(ref.get("locator") or "")
        current_digest = current_by_locator.get(locator)
        if ref.get("kind") == "repository" and current_digest:
            ref["content_sha256"] = current_digest
            changed = True
        rebound.append(ref)
    return rebound if changed else None


def _combine_provider_results(
    results: list[ProviderResult],
    *,
    decision: Any | None = None,
) -> ProviderResult:
    """Preserve the final decision while accounting for every provider attempt."""

    last = results[-1]
    if len(results) == 1 and decision is None:
        return last

    def summed(name: str) -> int | None:
        values = [getattr(item, name) for item in results]
        return (
            None
            if all(value is None for value in values)
            else sum(value or 0 for value in values)
        )

    return ProviderResult(
        decision=last.decision if decision is None else decision,
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
        attempt_count=sum(item.attempt_count for item in results),
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
    unfinished = [
        str(item).strip() for item in review.unfinished_work if str(item).strip()
    ]
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
        pattern, trigger = _normalize_rule_candidate_fields(
            str(pattern),
            str(candidate.trigger),
        )
        return {
            **common,
            "session_id": job.session_id,
            "pattern": pattern,
            "trigger": trigger,
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


def _normalize_rule_candidate_fields(pattern: str, trigger: str) -> tuple[str, str]:
    """Repair only an obvious provider reversal of rule condition and behavior."""

    normalized_pattern = " ".join(pattern.split())
    normalized_trigger = " ".join(trigger.split())
    condition_prefixes = (
        "when ",
        "whenever ",
        "if ",
        "after ",
        "before ",
        "during ",
        "当",
        "如果",
        "在",
    )
    condition_suffixes = (
        "时",
        "时。",
        "后",
        "后。",
        "前",
        "前。",
        "情况下",
        "情况下。",
    )
    action_markers = (
        "must ",
        "should ",
        "create ",
        "preserve ",
        "record ",
        "requeue ",
        "创建",
        "保存",
        "记录",
        "重新处理",
        "重新入队",
        "必须",
        "应当",
        "应该",
    )

    def looks_like_condition(value: str) -> bool:
        lowered = value.casefold()
        return lowered.startswith(condition_prefixes) or value.endswith(
            condition_suffixes
        )

    def looks_like_action(value: str) -> bool:
        lowered = value.casefold()
        return any(marker in lowered for marker in action_markers)

    if (
        looks_like_condition(normalized_pattern)
        and not looks_like_condition(normalized_trigger)
        and looks_like_action(normalized_trigger)
    ):
        return normalized_trigger, normalized_pattern
    return normalized_pattern, normalized_trigger


def _governed_candidate_id(result: dict[str, Any]) -> str | None:
    """Read the stable id returned by one kind-specific suggest handler."""

    for key in ("entry_id", "candidate_id", "fact_id"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    return None


def _sum_provider_metric(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return int(left or 0) + int(right or 0)


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
    category = str(getattr(candidate, "category", None) or "").lower()
    candidate_statement = str(
        getattr(candidate, "content", None)
        or getattr(candidate, "pattern", None)
        or getattr(candidate, "evidence", None)
        or ""
    ).strip()
    normalized_statement = " ".join(candidate_statement.casefold().split())
    normalized_unfinished = {
        " ".join(str(item).casefold().split())
        for item in review.unfinished_work
        if str(item).strip()
    }
    # A handoff category, or an exact copy of a listed next step, is task
    # narration.  Do not reject a real durable rule merely because it contains
    # words such as "unfinished" while specifying how to handle that state.
    if review.unfinished_work and (
        any(
            marker in category
            for marker in ("handoff", "unfinished", "task", "后续", "待办", "未完成")
        )
        or normalized_statement in normalized_unfinished
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
    """Keep a legacy ranking hint from vetoing a valid separated candidate.

    Confidence is not current knowledge and cannot establish truth.  The
    compatibility candidate tables still require a value, so an omitted model
    hint receives the neutral existing-default value instead of converting an
    otherwise valid evidence-backed point into a failed session.
    """

    return 0.5 if candidate.confidence is None else float(candidate.confidence)


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
        if (
            not is_meaningful_session_summary(summary)
            and path is not None
            and path.is_file()
        ):
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
        "dispatch_generation": current.get("dispatch_generation"),
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
    if trigger_id is not None and job.session_id != trigger_id:
        # This job belongs to backlog work offered in the same batch. Keep its
        # evidence in the batch outcome without rebinding the active Hook's
        # generation-scoped receipt to another session.
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={"last_background_completion": verified_completion},
        )
        return completion
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
