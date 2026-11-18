"""Recover an interrupted finite Dream task on an ordinary native wake.

The queue is only a pointer. The original source, run and cumulative account
remain authoritative, and are reopened again by the detached owner.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_mem.autonomous.authorization import background_status
from harness_mem.autonomous.executors.task_budget import (
    maintenance_task_scope, read_task_budget_receipt,
)


def _require_origin(condition: Any, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _queue_origin_id(run: Any) -> str:
    """A typed child keeps its parent's immutable queue pointer."""
    checkpoint = run.continuation
    source = checkpoint.get("terminal_source_coverage_origin_run_id")
    report = checkpoint.get("terminal_report_origin_run_id")
    _require_origin(not (source is not None and report is not None), "continuation_child_origin_ambiguous")
    pinned = source if source is not None else report
    if pinned is not None:
        _require_origin(isinstance(pinned, str) and bool(pinned) and pinned != run.id,
                        "continuation_child_origin_invalid")
    return pinned or run.id


def _report_native_work_pending(checkpoint: dict[str, Any]) -> bool:
    """Only completed frozen signals can close without another model call."""
    signals = checkpoint.get("signals")
    completed = checkpoint.get("completed_signal_indexes")
    _require_origin(isinstance(signals, list) and isinstance(completed, list)
                    and all(type(index) is int and 0 <= index < len(signals) for index in completed)
                    and len(completed) == len(set(completed)), "terminal_report_progress_invalid")
    return len(completed) != len(signals)


async def _terminal_origin(backend: Any, *, project_name: str, project_root: str,
                           config: Any, host_client: str,
                           origin_run_id: str | None = None) -> tuple[Any, str, str, str, str]:
    """Existing source-coverage obligations precede a new report-only child."""
    from harness_mem.commands.dream_source_coverage import bound_terminal_source_coverage_origin
    try:
        origin, generation, trigger, source_job = await bound_terminal_source_coverage_origin(
            backend, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client, origin_run_id=origin_run_id)
    except ValueError as exc:
        # Unknown/active usage, changed scope, invalid pointers and exhausted
        # accounts must never fall through to a different task or transport.
        if str(exc) != "no_terminal_pending_coverage":
            raise
        from harness_mem.commands.dream_report_continuation import bound_terminal_report_origin
        origin, generation, trigger, source_job = await bound_terminal_report_origin(
            backend, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client, origin_run_id=origin_run_id)
        return origin, generation, trigger, source_job, "report"
    return origin, generation, trigger, source_job, "coverage"


async def _bound_source_account(backend: Any, *, run: Any, project_name: str,
                                project_root: str, config: Any, host_client: str,
                                source_job_id: str | None = None,
                                require_remaining: bool = True,
                                require_exhausted: bool = False,
                                failure_account: dict[str, Any] | None = None,
                                generation: str | None = None,
                                trigger_id: str | None = None) -> tuple[Any, str, str]:
    """Only immutable task/source facts; callers own their distinct state gates."""
    from harness_mem.commands.evidence_admission import _source_report_context
    from harness_mem.maintenance_lock import maintenance_is_locked

    require = _require_origin
    auth = background_status(config, client=host_client)
    require(auth.ready and auth.selected_cli == host_client, "continuation_not_authorized")
    require(run is not None and run.project_name == project_name, "continuation_account_mismatch")
    checkpoint = run.continuation
    require(isinstance(checkpoint, dict) and checkpoint.get("version") == "dream-slices-v3",
            "continuation_contract_missing")
    scope = checkpoint.get("maintenance_scope")
    require(isinstance(scope, dict), "continuation_account_missing")
    original_generation, original_trigger = scope.get("dispatch_generation"), scope.get("trigger_id")
    require(isinstance(original_generation, str) and bool(original_generation)
            and isinstance(original_trigger, str) and bool(original_trigger),
            "continuation_account_missing")
    require((generation is None or generation == original_generation)
            and (trigger_id is None or trigger_id == original_trigger), "continuation_pointer_mismatch")
    require(not maintenance_is_locked(backend.data_dir, trigger_id=original_trigger),
            "exclusive_maintenance_run_active")
    task_scope = maintenance_task_scope(original_trigger, original_generation)
    receipt = read_task_budget_receipt(Path(backend.data_dir), task_scope)
    require(isinstance(receipt, dict) and receipt.get("task_scope") == task_scope
            and receipt.get("host_client") == host_client, "continuation_account_mismatch")
    fields = ("max_calls", "max_seconds", "max_input_tokens", "max_output_tokens",
              "host_max_output_tokens")
    bounds = {key: getattr(config, "task_model_budget_" + key) for key in fields}
    require(receipt.get("bounds") == bounds, "continuation_bounds_changed")
    calls = receipt.get("calls")
    require(isinstance(calls, list) and bool(calls), "continuation_usage_missing")
    failed_call_id = None
    if failure_account is not None:
        from harness_mem.commands.dream_source_coverage import _digest
        require(not require_remaining and not require_exhausted,
                "continuation_failure_bookkeeping_only")
        require(isinstance(failure_account, dict) and set(failure_account) == {
            "contract", "task_scope", "ledger_sha256", "failed_call_id",
            "failed_call_sha256", "completed_prefix_sha256"},
            "continuation_failure_account_invalid")
        last = calls[-1]
        usage = last.get("usage") if isinstance(last, dict) else None
        known_failure = (isinstance(usage, dict)
            and set(usage) == {"input_tokens", "output_tokens", "duration_seconds"}
            and last.get("usage_exact") is True and all(
                type(usage[key]) in ((int, float) if key == "duration_seconds" else (int,))
                and math.isfinite(usage[key]) and usage[key] >= 0 for key in usage))
        unknown_failure = (isinstance(last, dict) and last.get("usage_exact") is False
            and usage == {"input_tokens": None, "output_tokens": None, "duration_seconds": None})
        require(isinstance(last, dict) and failure_account.get("contract") == "source-failure-bookkeeping-v1"
                and failure_account.get("task_scope") == task_scope
                and failure_account.get("ledger_sha256") == _digest(receipt)
                and failure_account.get("failed_call_sha256") == _digest(last)
                and failure_account.get("completed_prefix_sha256") == _digest(calls[:-1])
                and failure_account.get("failed_call_id") == last.get("call_id")
                and last.get("status") == "failed" and (known_failure or unknown_failure)
                and last.get("model_completion") is False
                and type(last.get("reconciled_at")) in (int, float)
                and math.isfinite(last["reconciled_at"])
                and type(last.get("reserved_at")) in (int, float)
                and math.isfinite(last["reserved_at"])
                and 0 <= last["reserved_at"] <= last["reconciled_at"],
                "continuation_failure_account_changed")
        failed_call_id = last.get("call_id")
    totals = {"calls": len(calls), "seconds": 0.0, "input_tokens": 0, "output_tokens": 0}
    source_jobs: set[str] = set()
    call_ids: set[str] = set()
    for call in calls:
        if failed_call_id is not None and call is calls[-1] and call.get("usage_exact") is False:
            require(isinstance(failed_call_id, str) and bool(failed_call_id)
                    and failed_call_id not in call_ids, "continuation_call_identity_invalid")
            call_ids.add(failed_call_id)
            continue  # Preserve this unknown call; it grants no inference credit.
        require(isinstance(call, dict) and (call.get("status") == "completed"
                or (failure_account is not None and call.get("status") == "failed"))
                and call.get("usage_exact") is True, "continuation_usage_unknown_or_active")
        call_id = call.get("call_id")
        require(isinstance(call_id, str) and bool(call_id) and call_id not in call_ids,
                "continuation_call_identity_invalid")
        call_ids.add(call_id)
        usage = call.get("usage")
        require(isinstance(usage, dict), "continuation_usage_missing")
        for key in ("input_tokens", "output_tokens", "duration_seconds"):
            value = usage.get(key)
            require(type(value) in ((int, float) if key == "duration_seconds" else (int,))
                    and math.isfinite(value) and value >= 0, "continuation_usage_invalid")
            totals["seconds" if key == "duration_seconds" else key] += value
        if call.get("phase") == "source" and isinstance(call.get("slice_id"), str):
            prefix = "source-decide:"
            if call["slice_id"].startswith(prefix):
                source_jobs.add(call["slice_id"][len(prefix):])
    require(all(type(bounds["max_" + key]) is int and bounds["max_" + key] > 0 for key in totals),
            "continuation_bounds_changed")
    if require_remaining:
        require(all(totals[key] < bounds["max_" + key] for key in totals), "continuation_budget_exhausted")
    if require_exhausted:
        require(not require_remaining and any(totals[key] >= bounds["max_" + key] for key in totals),
                "continuation_budget_not_exhausted")
    prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
    noted_jobs = {note[len(prefix):].strip() for note in (run.notes or []) for prefix in prefixes
                  if note.startswith(prefix)}
    require(len(source_jobs) == 1 and (source_jobs == noted_jobs if source_job_id is None
            else source_jobs == {source_job_id}), "continuation_source_binding_missing")
    source_job = backend.transcript_store.get_distill_job(next(iter(source_jobs)))
    root = str(Path(project_root).resolve())
    require(source_job is not None and source_job.status == "completed"
            and source_job.project_name == project_name
            and str(Path(source_job.project_root).resolve()) == root
            and source_job.client == host_client and source_job.session_id == original_trigger,
            "continuation_source_scope_mismatch")
    revision, _rendering, _raw = _source_report_context(
        backend, project_name=project_name, source_id=source_job.source_id,
        source_revision=source_job.source_revision,
    )
    require(revision.client == host_client and revision.session_id == original_trigger
            and str(Path(revision.project_root).resolve()) == root,
            "continuation_source_scope_mismatch")
    return run, original_generation, original_trigger


async def _bound_origin(backend: Any, *, project_name: str, project_root: str,
                        config: Any, host_client: str, run_id: str,
                        generation: str | None = None,
                        trigger_id: str | None = None,
                        allow_exhausted_report: bool = False,
                        allow_failed_source_bookkeeping: bool = False) -> tuple[Any, str, str]:
    require = _require_origin
    run = await backend.structured_store.get_dream_run(run_id)
    require(run is not None and run.project_name == project_name
            and run.status == "continuing", "continuation_not_resumable")
    latest = await backend.structured_store.list_dream_runs(project_name, limit=1)
    require(bool(latest) and latest[0].id == run_id, "continuation_superseded")
    checkpoint = run.continuation
    require(isinstance(checkpoint, dict) and checkpoint.get("version") == "dream-slices-v3",
            "continuation_contract_missing")
    _queue_origin_id(run)
    report_origin = checkpoint.get("terminal_report_origin_run_id")
    source_origin = checkpoint.get("terminal_source_coverage_origin_run_id")
    count, maximum = checkpoint.get("slice_count"), checkpoint.get("max_slices")
    require(type(count) is int and type(maximum) is int and 0 <= count <= maximum
            and (report_origin is not None or count < maximum
                 or (allow_failed_source_bookkeeping and isinstance(source_origin, str))),
            "continuation_slices_exhausted")
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=max(1, config.dream_auto_max_runtime_seconds))
    for job in backend.reflection_job_store.list(
        project_name=project_name, status="processing", kind="dream",
    ):
        updated = job.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        require(updated < stale_before, "continuation_processing_active")
    if report_origin is not None:
        from harness_mem.commands.dream_report_continuation import bound_report_child
        arguments = dict(project_name=project_name, project_root=project_root, config=config,
            host_client=host_client, child_run_id=run.id, origin_run_id=report_origin,
            require_remaining=_report_native_work_pending(checkpoint))
        try:
            child, child_generation, child_trigger = await bound_report_child(backend, **arguments)
        except ValueError as exc:
            if not allow_exhausted_report or str(exc) != "continuation_budget_exhausted":
                raise
            child, child_generation, child_trigger = await bound_report_child(
                backend, **arguments, exhausted_bookkeeping=True)
        require(child.id == run.id and (generation is None or generation == child_generation)
                and (trigger_id is None or trigger_id == child_trigger), "continuation_pointer_mismatch")
        return child, child_generation, child_trigger
    require_remaining = True
    pinned = checkpoint.get("terminal_source_coverage_origin_run_id")
    if isinstance(pinned, str):
        origin = await backend.structured_store.get_dream_run(pinned)
        if origin is not None and origin.status == "failed":
            ledger = origin.continuation.get("source_coverage") or {}
            terminal = {"applied", "no_write", "unresolved", "failed", "not_applicable"}
            require_remaining = any((ledger.get(key) or {}).get("status") not in terminal
                                    for key in origin.continuation.get("source_coverage_pending_ids") or [])
    try:
        if count == maximum:
            raise ValueError("continuation_slices_exhausted")
        return await _bound_source_account(
            backend, run=run, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client, generation=generation, trigger_id=trigger_id,
            require_remaining=require_remaining,
        )
    except ValueError as exc:
        if (not allow_failed_source_bookkeeping or not isinstance(pinned, str)
                or str(exc) not in {"continuation_usage_unknown_or_active", "continuation_slices_exhausted"}):
            raise
        from harness_mem.commands.dream_source_coverage import bound_failed_source_child
        child, child_generation, child_trigger = await bound_failed_source_child(
            backend, child_run_id=run.id, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client)
        require(child.id == run.id and (generation is None or generation == child_generation)
                and (trigger_id is None or trigger_id == child_trigger), "continuation_pointer_mismatch")
        return child, child_generation, child_trigger


async def enqueue_bound_continuation(backend: Any, *, project_name: str,
                                     project_root: str, config: Any,
                                     host_client: str) -> dict[str, Any]:
    """Wake-up scheduling performs no semantic work and never restages source."""
    from harness_mem.hook_background import dispatch_bound_continuation

    # Match the scheduler's current run; never resurrect an older superseded run.
    runs = await backend.structured_store.list_dream_runs(project_name, limit=1)
    run_id = runs[0].id if runs else None
    try:
        if runs and runs[0].status == "continuing":
            _run, generation, trigger = await _bound_origin(
                backend, project_name=project_name, project_root=project_root,
                config=config, host_client=host_client, run_id=run_id, allow_exhausted_report=True,
                allow_failed_source_bookkeeping=True)
            # Keep the same queue identity across creation of a coverage-only
            # carrier; a wake must not replace the active origin pointer.
            run_id = _queue_origin_id(_run)
        else:
            _run, generation, trigger, _source_job, _kind = await _terminal_origin(
                backend, project_name=project_name, project_root=project_root,
                config=config, host_client=host_client)
            run_id = _run.id
        result = dispatch_bound_continuation(
            Path(backend.data_dir), project_root=Path(project_root), client=host_client,
            trigger_id=trigger, generation=generation, resume_run_id=run_id,
        )
        return {"status": "queued", "run_id": run_id, "generation": generation,
                "spawned": result.spawned, "coalesced": result.coalesced}
    except Exception as exc:
        reason = str(exc)[:256] if isinstance(exc, ValueError) else type(exc).__name__
        if reason in {"no_terminal_pending_coverage", "no_terminal_report_origin"}:
            reason = "no_current_continuation"
        return {"status": "skipped", "run_id": run_id,
                "reason": reason}


async def run_bound_continuation(backend: Any, *, project_name: str, project_root: str,
                                 config: Any, host_client: str, resume_run_id: str,
                                 trigger_id: str | None) -> dict[str, Any]:
    """Resume the bound account through Dream's existing finite slice owner."""
    from harness_mem.commands.dream import dream_auto_tick
    from harness_mem.hook_background import background_generation_from_env, heartbeat_background_worker

    try:
        generation = background_generation_from_env()
        if os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1" or not generation:
            raise ValueError("continuation_detached_owner_required")
        requested = await backend.structured_store.get_dream_run(resume_run_id)
        dream: dict[str, Any] = {}
        active_run_id = resume_run_id
        if requested is not None and requested.status == "failed":
            latest = await backend.structured_store.list_dream_runs(project_name, limit=1)
            child = latest[0] if latest else None
            if (child is not None and child.status == "continuing"
                    and _queue_origin_id(child) == requested.id):
                if child.continuation.get("terminal_source_coverage_origin_run_id"):
                    await _bound_origin(
                        backend, project_name=project_name, project_root=project_root, config=config,
                        host_client=host_client, run_id=child.id, generation=generation,
                        trigger_id=trigger_id, allow_failed_source_bookkeeping=True)
                else:
                    await _bound_source_account(
                        backend, run=requested, project_name=project_name, project_root=project_root,
                        config=config, host_client=host_client, generation=generation,
                        trigger_id=trigger_id, require_remaining=False)
                active_run_id = child.id
            else:
                origin, original_generation, original_trigger, _source_job, kind = await _terminal_origin(
                    backend, project_name=project_name, project_root=project_root,
                    config=config, host_client=host_client, origin_run_id=requested.id)
                _require_origin(generation == original_generation and trigger_id == original_trigger,
                                "continuation_pointer_mismatch")
                if not heartbeat_background_worker(
                    Path(backend.data_dir), project_root=Path(project_root), client=host_client):
                    raise ValueError("background_worker_lease_lost")
                dream = await dream_auto_tick(
                    backend, project_name=project_name, project_root=project_root, config=config,
                    source="ide_hook", trigger_id=original_trigger, trigger_job_id=None,
                    host_client=host_client,
                    **({"report_origin_run_id": origin.id} if kind == "report" else
                       {"coverage_origin_run_id": origin.id}))
                active_run_id = dream.get("run_id") or ""
        if not dream or dream.get("status") == "continuing":
            run, _generation, trigger = await _bound_origin(
                backend, project_name=project_name, project_root=project_root, config=config,
                host_client=host_client, run_id=active_run_id, generation=generation,
                trigger_id=trigger_id, allow_exhausted_report=True,
                allow_failed_source_bookkeeping=True)
            if run.continuation.get("terminal_source_coverage_origin_run_id"):
                from harness_mem.commands.dream_source_coverage import close_failed_source_child
                dream = await close_failed_source_child(
                    backend, child_run_id=run.id, project_name=project_name, project_root=project_root,
                    config=config, host_client=host_client, generation=generation, trigger_id=trigger)
            if run.continuation.get("terminal_report_origin_run_id") and _report_native_work_pending(run.continuation):
                from harness_mem.commands.dream_report_continuation import close_exhausted_report_child
                dream = await close_exhausted_report_child(
                    backend, child_run_id=run.id, project_name=project_name, project_root=project_root,
                    config=config, host_client=host_client, generation=generation, trigger_id=trigger)
            remaining = run.continuation["max_slices"] - run.continuation["slice_count"]
            if run.continuation.get("terminal_report_origin_run_id") and not _report_native_work_pending(run.continuation):
                remaining = max(1, remaining)  # Existing child bookkeeping, no new slice/model reservation.
            for _ in range(0 if dream.get("status") == "failed" else remaining):
                await _bound_origin(
                    backend, project_name=project_name, project_root=project_root, config=config,
                    host_client=host_client, run_id=active_run_id, generation=generation, trigger_id=trigger)
                if not heartbeat_background_worker(
                    Path(backend.data_dir), project_root=Path(project_root), client=host_client):
                    raise ValueError("background_worker_lease_lost")
                dream = await dream_auto_tick(
                    backend, project_name=project_name, project_root=project_root, config=config,
                    source="ide_hook", trigger_id=trigger, trigger_job_id=None,
                    host_client=host_client, resume_run_id=active_run_id)
                if dream.get("status") != "continuing":
                    break
        else:
            trigger = trigger_id
        from harness_mem.autonomous.worker import record_post_turn_maintenance_outcome
        record_post_turn_maintenance_outcome(
            backend.data_dir, project_name=project_name, project_root=project_root,
            trigger_id=trigger, dispatch_generation=generation, dream=dream,
        )
        return {"action": "post-turn-maintenance", "success": dream.get("status") != "failed",
                "status": "in_progress" if dream.get("status") == "continuing" else dream.get("status", "failed"),
                "resume_run_id": resume_run_id, "dream_tick": dream,
                "evidence_packet": None, "distill_job": None}
    except Exception as exc:
        return {"action": "post-turn-maintenance", "success": False, "status": "failed",
                "resume_run_id": resume_run_id, "reason": str(exc)[:256]
                if isinstance(exc, ValueError) else type(exc).__name__,
                "evidence_packet": None, "distill_job": None, "dream_tick": None}
