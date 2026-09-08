"""v3.1 Auto Dream Memory Maintenance business command."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from harness_mem.commands.evidence_admission import reopen_dream_knowledge_sources
from harness_mem.commands.dream_assimilation import (
    DreamAssimilationCandidate,
    apply_dream_assimilation,
    prepare_dream_assimilation,
    validate_dream_assimilation_decision,
)
from harness_mem.autonomous.models import (
    AssimilationDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.authorization import background_on, background_status
from harness_mem.autonomous.provider import ProviderError
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import (
    DreamItem,
    DreamRun,
    KnowledgeEntry,
    ReflectionJob,
)
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


DreamSource = Literal["user", "agent", "ide_hook", "scheduler"]


@dataclass(frozen=True)
class DreamSchedulerDecision:
    eligible: bool
    reason: str
    last_run_id: str | None = None
    next_eligible_at: datetime | None = None


@dataclass(frozen=True)
class DreamRecheckSignal:
    """One non-persisted maintenance hypothesis about current knowledge."""

    kind: Literal["duplicate", "conflict", "stale", "feedback"]
    target_ids: tuple[str, ...]
    proposed_action: Literal["merge", "delete", "replace"]
    risk: Literal["medium", "high"]
    reason: str
    cause_id: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _detect_separated_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None,
) -> list[DreamRecheckSignal]:
    """Find recheck hypotheses without creating candidate/evidence rows.

    Dream signals are not candidate facts. A single-entry signal may proceed
    through source reopening and trusted confirmation; a multi-entry signal is
    closed without changing current memory when a safe comparison is not
    available. This prevents a recurring scheduler from filling the temporary
    job workspace with unverified pseudo-knowledge.
    """

    store = backend.structured_store.knowledge_store
    current = await store.list_entries(project_name)
    signals: list[DreamRecheckSignal] = []
    seen: set[tuple[str, tuple[str, ...], str | None]] = set()

    def add(signal: DreamRecheckSignal) -> None:
        key = (signal.kind, signal.target_ids, signal.cause_id)
        if key not in seen:
            seen.add(key)
            signals.append(signal)

    duplicate_groups: dict[str, list[KnowledgeEntry]] = {}
    for entry in current:
        normalized = " ".join(entry.statement.casefold().split())
        if normalized:
            duplicate_groups.setdefault(normalized, []).append(entry)
    for group in duplicate_groups.values():
        if len(group) > 1:
            add(
                DreamRecheckSignal(
                    kind="duplicate",
                    target_ids=tuple(sorted(entry.id for entry in group)),
                    proposed_action="merge",
                    risk="medium",
                    reason="Dream detected duplicate current knowledge.",
                )
            )

    competing_groups: dict[tuple[tuple[str, ...], str], list[KnowledgeEntry]] = {}
    for entry in current:
        key = (
            tuple(part.casefold() for part in entry.module_path),
            entry.title.casefold(),
        )
        competing_groups.setdefault(key, []).append(entry)
    for group in competing_groups.values():
        statements = {" ".join(entry.statement.casefold().split()) for entry in group}
        if len(group) > 1 and len(statements) > 1:
            add(
                DreamRecheckSignal(
                    kind="conflict",
                    target_ids=tuple(sorted(entry.id for entry in group)),
                    proposed_action="replace",
                    risk="high",
                    reason="Dream detected competing current knowledge.",
                )
            )

    reverify_before = _now() - timedelta(days=180)
    for entry in current:
        if entry.verified_at is not None and entry.verified_at <= reverify_before:
            add(
                DreamRecheckSignal(
                    kind="stale",
                    target_ids=(entry.id,),
                    proposed_action="delete",
                    risk="medium",
                    reason="Dream selected an aged source-backed knowledge entry for recheck.",
                )
            )

    feedback_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="context_outcome",
        target_kind="knowledge_entry",
        limit=200,
    )
    latest_feedback: dict[str, Any] = {}
    for signal in feedback_signals:
        latest_feedback.setdefault(signal.target_id, signal)
    for signal in latest_feedback.values():
        if signal.value is None or signal.value > 0:
            continue
        feedback_entry = await store.get_entry(
            signal.target_id,
            project_name=project_name,
            project_root=project_root,
        )
        if feedback_entry is None:
            continue
        add(
            DreamRecheckSignal(
                kind="feedback",
                target_ids=(feedback_entry.id,),
                proposed_action="delete",
                risk="medium" if signal.value == 0 else "high",
                reason=(
                    "Dream selected ignored retrieval feedback for source-backed recheck."
                    if signal.value == 0
                    else "Dream selected misleading retrieval feedback for source-backed recheck."
                ),
                cause_id=signal.id,
            )
        )
    return signals


def _dream_provider_from_config(
    config: MergedConfig | dict[str, Any] | None,
    *,
    host_client: str | None = None,
) -> Any | None:
    """Return the host CLI executor when the project authorized background semantic work."""

    if not background_on(config):
        return None
    if not isinstance(config, MergedConfig):
        return None
    from harness_mem.autonomous.executors.registry import build_semantic_executor
    from harness_mem.commands.support import detect_runtime_client, normalize_client_name

    client = normalize_client_name(host_client) if host_client else detect_runtime_client()
    configured_cli = str(config.distill_autonomous_cli or "current")
    if configured_cli == "current" and client is None:
        return None
    return build_semantic_executor(config, client or "unknown")


async def _run_source_backed_recheck_group(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path,
    entries: list[KnowledgeEntry],
    signal: DreamRecheckSignal,
    run_id: str,
    provider: Any | None,
    allow_retire: bool,
) -> list[DreamItem]:
    """Compare, verify, and assimilate a bounded current-knowledge group."""

    store = backend.structured_store.knowledge_store
    source_kind = f"knowledge_{signal.kind}"
    if provider is None:
        return [
            DreamItem(
                source_kind=f"knowledge_{signal.kind}",
                source_id=entry.id,
                risk=signal.risk,
                proposed_action=signal.proposed_action,
                final_action="failed",
                reason="Dream could not run because no background CLI was available.",
                result={"source_status": "provider_not_selected", "truth_change": "none"},
                error="background CLI unavailable",
            )
            for entry in entries
        ]

    rechecked: list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]] = []
    for entry in entries:
        sources = await store.list_sources(entry.id)
        validation, reopened, effective_sources = await reopen_dream_knowledge_sources(
            backend,
            project_name=project_name,
            sources=sources,
            project_root=project_root,
        )
        if validation.verification_outcome != "verified":
            return [
                _skipped_recheck_item(
                    candidate,
                    signal=signal,
                    reason=(
                        "Dream could not reopen every policy-eligible current source "
                        "for this comparison; current knowledge was left unchanged."
                    ),
                    source_status=str(validation.verification_outcome or "unverified"),
                )
                for candidate in entries
            ]
        if any(item.truncated for item in reopened):
            return [
                _skipped_recheck_item(
                    candidate,
                    signal=signal,
                    reason=(
                        "Dream reopened only a bounded source excerpt; current knowledge "
                        "was left unchanged rather than inferring a semantic result."
                    ),
                    source_status="truncated",
                )
                for candidate in entries
            ]
        if not any(item.content for item in reopened):
            return [
                _skipped_recheck_item(
                    candidate,
                    signal=signal,
                    reason="Dream reopened no readable source text; current knowledge was left unchanged.",
                    source_status="unreadable",
                )
                for candidate in entries
            ]
        rechecked.append((entry, validation, tuple(reopened), tuple(effective_sources)))

    verification_manifest = {
        "contract_version": "dream-source-recheck-v2",
        "candidates": [
            {
                "candidate_index": index,
                "statement": entry.statement,
                "source_kind": validation.evidence_basis,
            }
            for index, (entry, validation, _reopened, _sources) in enumerate(rechecked)
        ],
        "source_excerpts": [
            {
                "candidate_index": index,
                "source_kind": item.source_kind,
                "content": item.content,
            }
            for index, (_entry, _validation, reopened, _sources) in enumerate(rechecked)
            for item in reopened
            if item.content
        ],
    }
    verification_result = await asyncio.to_thread(
        provider.verify,
        verification_manifest,
        runtime_dir=Path(backend.data_dir) / "autonomous" / "provider-runtime",
    )
    if not isinstance(verification_result.decision, CandidateVerificationDecision):
        raise ProviderError(
            "Dream provider returned an unexpected verification decision",
            kind="unrecoverable",
        )
    verification_points = list(verification_result.decision.points)
    if (
        len(verification_points) != len(rechecked)
        or {point.candidate_index for point in verification_points}
        != set(range(len(rechecked)))
    ):
        raise ProviderError(
            "Dream provider verification must cover every source recheck exactly once",
            kind="unrecoverable",
        )
    by_index = {point.candidate_index: point for point in verification_points}
    prepared = prepare_dream_assimilation(
        project_name=project_name,
        project_root=project_root,
        run_id=run_id,
        signal_kind=signal.kind,
        candidates=[
            DreamAssimilationCandidate(
                candidate_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        "harness-mem:dream-recheck:"
                        f"{run_id}:{signal.kind}:{entry.id}:{signal.cause_id or ''}",
                    )
                ),
                entry=entry,
                sources=effective_sources,
                semantic_support=by_index[index].semantic_support,
                future_scope=by_index[index].future_scope,
                verification_reason=by_index[index].reason,
                source_excerpts=tuple(
                    {
                        "source_kind": item.source_kind,
                        "content": str(item.content),
                    }
                    for item in reopened
                    if item.content
                ),
            )
            for index, (entry, _validation, reopened, effective_sources) in enumerate(rechecked)
        ],
    )
    assimilate = getattr(provider, "assimilate", None)
    if not callable(assimilate):
        raise ProviderError(
            "Dream provider does not implement comparative assimilation",
            kind="setup_required",
        )
    assimilation_result = await asyncio.to_thread(
        assimilate,
        prepared.manifest,
        runtime_dir=Path(backend.data_dir) / "autonomous" / "provider-runtime",
    )
    if not isinstance(assimilation_result.decision, AssimilationDecision):
        raise ProviderError(
            "Dream provider returned an unexpected assimilation decision",
            kind="unrecoverable",
        )
    plan = validate_dream_assimilation_decision(prepared, assimilation_result.decision)
    if not allow_retire:
        blocked = [
            point for point in plan if point["disposition"] in {"reject", "refine", "replace"}
        ]
        if blocked:
            return [
                _skipped_recheck_item(
                    entry,
                    signal=signal,
                    reason="Dream policy disabled the proposed current-knowledge change.",
                    source_status="policy_disabled",
                )
                for entry in entries
            ]
    outcomes = await apply_dream_assimilation(
        backend,
        prepared=prepared,
        plan=plan,
    )
    return [
        _dream_item_from_assimilation_outcome(
            outcome,
            signal=signal,
            source_kind=source_kind,
        )
        for outcome in outcomes
    ]


def _skipped_recheck_item(
    entry: KnowledgeEntry,
    *,
    signal: DreamRecheckSignal,
    reason: str,
    source_status: str,
) -> DreamItem:
    return DreamItem(
        source_kind=f"knowledge_{signal.kind}",
        source_id=entry.id,
        risk=signal.risk,
        proposed_action=signal.proposed_action,
        final_action="skipped",
        reason=reason,
        result={"source_status": source_status, "truth_change": "none"},
    )


def _dream_item_from_assimilation_outcome(
    outcome: dict[str, Any],
    *,
    signal: DreamRecheckSignal,
    source_kind: str,
) -> DreamItem:
    status = str(outcome.get("status") or "")
    if status == "source_changed":
        return DreamItem(
            source_kind=source_kind,
            source_id=str(outcome["entry_id"]),
            risk=signal.risk,
            proposed_action=signal.proposed_action,
            final_action="skipped",
            reason=str(outcome["reason"]),
            result={"source_status": "changed_during_assimilation", "truth_change": "none"},
        )
    if status == "rejected":
        return DreamItem(
            source_kind=source_kind,
            source_id=str(outcome["entry_id"]),
            risk=signal.risk,
            proposed_action=signal.proposed_action,
            final_action="rejected",
            reason=str(outcome["reason"]),
            result={"truth_change": "none"},
        )
    if status != "applied":
        raise ValueError("Dream assimilation returned an unknown outcome")
    result = {
        key: value
        for key, value in outcome.items()
        if key in {"truth_change", "truth_ids"}
    }
    return DreamItem(
        source_kind=source_kind,
        source_id=str(outcome["entry_id"]),
        risk=signal.risk,
        proposed_action=signal.proposed_action,
        final_action="applied",
        reason=str(outcome["reason"]),
        result=result,
    )


async def dream_once(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None = None,
    config: MergedConfig | dict[str, Any] | None = None,
    source: DreamSource = "agent",
    reflection_job_id: str | None = None,
    deadline: datetime | None = None,
    semantic_provider: Any | None = None,
    host_client: str | None = None,
) -> DreamRun:
    """Run one Dream pass and close its ledger on any handled failure."""

    run_id = str(uuid4())
    try:
        return await _dream_once(
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            source=source,
            reflection_job_id=reflection_job_id,
            deadline=deadline,
            semantic_provider=semantic_provider,
            host_client=host_client,
            _run_id=run_id,
        )
    except Exception as exc:
        store = cast(LocalStructuredStore, backend.structured_store)
        run = await store.get_dream_run(run_id)
        if run is not None and run.status == "processing":
            completed_at = _now()
            run.status = "failed"
            run.completed_at = completed_at
            run.duration_ms = int(
                (completed_at - run.started_at).total_seconds() * 1000
            )
            run.notes = list(run.notes or [])
            run.notes.append(f"dream failed: {type(exc).__name__}")
            await store.save_dream_run(run)
        raise


async def _dream_once(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None = None,
    config: MergedConfig | dict[str, Any] | None = None,
    source: DreamSource = "agent",
    reflection_job_id: str | None = None,
    deadline: datetime | None = None,
    semantic_provider: Any | None = None,
    host_client: str | None = None,
    _run_id: str | None = None,
) -> DreamRun:
    """Run one Dream maintenance pass and persist its bounded job status."""
    store = cast(LocalStructuredStore, backend.structured_store)
    started_at = _now()
    notes: list[str] = []
    items: list[DreamItem] = []

    run_stub = DreamRun(
        id=_run_id or str(uuid4()),
        project_name=project_name,
        started_at=started_at,
        completed_at=None,
        status="processing",
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        items=[],
        notes=notes if notes else None,
    )
    await store.save_dream_run(run_stub)

    recheck_signals = await _detect_separated_rechecks(
        backend,
        project_name=project_name,
        project_root=project_root,
    )
    selected_provider = semantic_provider or _dream_provider_from_config(
        config,
        host_client=host_client,
    )

    async def persist_progress(*, check_deadline: bool = True) -> None:
        run_stub.items = list(items)
        run_stub.handling_summary = {}
        run_stub.model_post_init(None)
        if check_deadline and deadline is not None and _now() >= deadline:
            completed_at = _now()
            run_stub.status = "failed"
            run_stub.completed_at = completed_at
            run_stub.duration_ms = int(
                (completed_at - started_at).total_seconds() * 1000
            )
            run_stub.notes = list(run_stub.notes or [])
            run_stub.notes.append("dream runtime exceeded max_runtime_seconds")
            await store.save_dream_run(run_stub)
            raise TimeoutError("dream runtime exceeded max_runtime_seconds")
        await store.save_dream_run(run_stub)

    for signal in recheck_signals:
        await persist_progress()
        signal_entries: list[KnowledgeEntry] = []
        for target_id in signal.target_ids:
            entry = await backend.structured_store.knowledge_store.get_entry(
                target_id,
                project_name=project_name,
                project_root=project_root,
            )
            if entry is not None:
                signal_entries.append(entry)
        missing_target_ids = set(signal.target_ids) - {
            entry.id for entry in signal_entries
        }
        if missing_target_ids:
            items.append(
                DreamItem(
                    source_kind=f"knowledge_{signal.kind}",
                    source_id=":".join(sorted(missing_target_ids)),
                    risk=signal.risk,
                    proposed_action=signal.proposed_action,
                    final_action="skipped",
                    reason="Dream target is no longer current knowledge.",
                    result={"truth_change": "none"},
                )
            )
            continue
        if project_root is None:
            items.extend(
                _skipped_recheck_item(
                    entry,
                    signal=signal,
                    reason=(
                        "Dream has no project root for safe source reopening; "
                        "current knowledge was left unchanged."
                    ),
                    source_status="project_root_unavailable",
                )
                for entry in signal_entries
            )
            continue
        items.extend(
            await _run_source_backed_recheck_group(
                backend,
                project_name=project_name,
                project_root=str(project_root),
                entries=signal_entries,
                signal=signal,
                run_id=run_stub.id,
                provider=selected_provider,
                allow_retire=True,
            )
        )
        await persist_progress()

    completed_at = _now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    status: Literal["completed", "failed"] = (
        "failed"
        if any(item.final_action == "failed" for item in items)
        else "completed"
    )
    run = DreamRun(
        id=run_stub.id,
        project_name=project_name,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        items=items,
        duration_ms=duration_ms,
        notes=notes if notes else None,
    )
    await store.save_dream_run(run)
    return run


async def latest_dream_ledger(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    store = cast(LocalStructuredStore, backend.structured_store)
    run: DreamRun | None
    if run_id:
        run = await store.get_dream_run(run_id)
    else:
        runs = await store.list_dream_runs(project_name, limit=1)
        run = runs[0] if runs else None
    recent_ticks = _dream_tick_receipts(
        backend,
        project_name=project_name,
        limit=10,
    )
    latest_tick = recent_ticks[-1] if recent_ticks else None
    if run is None:
        return {
            "success": True,
            "project_name": project_name,
            "run": None,
            "last_tick": latest_tick,
            "recent_ticks": recent_ticks,
        }
    return {
        "success": True,
        "project_name": project_name,
        "run": run.to_dict(),
        "last_tick": latest_tick,
        "recent_ticks": recent_ticks,
    }


async def dream_status_snapshot(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    config: MergedConfig | None = None,
) -> dict[str, Any]:
    """Return read-only v3.1 dream status for doctor/status surfaces."""
    store = cast(LocalStructuredStore, backend.structured_store)
    runs = await store.list_dream_runs(project_name, limit=1)
    last_run = runs[0] if runs else None
    failed_items = 0
    processed_items = 0
    if last_run is not None:
        failed_items = int(last_run.handling_summary.get("failed", 0))
        processed_items = int(last_run.handling_summary.get("processed", 0))

    latest_tick = _latest_dream_tick_receipt(backend, project_name=project_name)
    payload: dict[str, Any] = {
        "enabled": bool(config.dream_auto_enabled) if config is not None else False,
        "last_tick": latest_tick,
        "last_tick_at": latest_tick.get("timestamp") if latest_tick else None,
        "last_tick_status": latest_tick.get("status") if latest_tick else None,
        "last_tick_reason": latest_tick.get("reason") if latest_tick else None,
        "last_run_id": last_run.id if last_run else None,
        "last_status": last_run.status if last_run else None,
        "last_started_at": _iso(last_run.started_at) if last_run else None,
        "last_completed_at": _iso(last_run.completed_at) if last_run else None,
        "last_processed": processed_items,
        "last_failed": failed_items,
        "scheduler_eligible": False,
        "scheduler_reason": "dream config unavailable",
        "next_eligible_at": None,
    }
    if config is None:
        return payload

    decision = await dream_scheduler_decision(
        backend,
        project_name=project_name,
        config=config,
    )
    payload.update(
        {
            "scheduler_eligible": decision.eligible,
            "scheduler_reason": decision.reason,
            "next_eligible_at": _iso(decision.next_eligible_at),
        }
    )
    return payload


async def _latest_project_activity(
    backend: LocalMemoryBackend,
    project_name: str,
) -> datetime | None:
    latest: datetime | None = None
    observations = await backend.verbatim_store.timeline(project_name, limit=1)
    for observation in observations:
        ts = observation.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if latest is None or ts > latest:
            latest = ts
    signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        limit=1,
    )
    if signals:
        ts = signals[0].recorded_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if latest is None or ts > latest:
            latest = ts
    return latest


async def dream_scheduler_decision(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    config: MergedConfig,
) -> DreamSchedulerDecision:
    if not config.dream_auto_enabled:
        return DreamSchedulerDecision(False, "dream.auto.enabled is false")
    store = cast(LocalStructuredStore, backend.structured_store)
    runs = await store.list_dream_runs(project_name, limit=1)
    last_run = runs[0] if runs else None
    latest_activity = await _latest_project_activity(backend, project_name)
    if latest_activity is None:
        return DreamSchedulerDecision(False, "no project activity to dream over")
    if last_run is not None and latest_activity <= last_run.started_at:
        return DreamSchedulerDecision(
            False,
            "no new project activity since the last dream run",
            last_run_id=last_run.id,
        )

    now = _now()
    min_interval = timedelta(hours=config.dream_auto_min_interval_hours)
    interval_at = last_run.started_at + min_interval if last_run is not None else now
    idle_at = latest_activity + timedelta(seconds=config.dream_auto_idle_seconds)
    interval_elapsed = now >= interval_at
    idle_elapsed = now >= idle_at
    if config.dream_auto_trigger == "interval":
        eligible = interval_elapsed
    elif config.dream_auto_trigger == "idle":
        eligible = idle_elapsed
    else:
        eligible = interval_elapsed or idle_elapsed

    if config.dream_auto_trigger == "interval":
        next_eligible_at = interval_at
    elif config.dream_auto_trigger == "idle":
        next_eligible_at = idle_at
    else:
        next_eligible_at = min(interval_at, idle_at)
    if not eligible:
        return DreamSchedulerDecision(
            False,
            "scheduler gates have not elapsed",
            last_run_id=last_run.id if last_run else None,
            next_eligible_at=next_eligible_at,
        )
    return DreamSchedulerDecision(
        True,
        "eligible for dream run",
        last_run_id=last_run.id if last_run else None,
        next_eligible_at=next_eligible_at,
    )


async def dream_auto_tick(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    config: MergedConfig,
    source: DreamSource = "agent",
    trigger_id: str | None = None,
    trigger_job_id: str | None = None,
    host_client: str | None = None,
) -> dict[str, Any]:
    from harness_mem.maintenance_lock import maintenance_is_locked

    if maintenance_is_locked(backend.data_dir, trigger_id=trigger_id):
        return {
            "success": True,
            "status": "skipped",
            "project_name": project_name,
            "reason": "exclusive_maintenance_run_active",
            "summary": {"processed": 0, "maintenance_excluded": True},
        }
    hook_session: dict[str, Any] | None = None
    if source == "ide_hook" and trigger_job_id:
        from harness_mem.commands.support import detect_runtime_client, normalize_client_name

        trigger_job = backend.transcript_store.get_distill_job(trigger_job_id)
        resolved_host_client = (
            normalize_client_name(host_client)
            if host_client
            else normalize_client_name(getattr(trigger_job, "client", None))
            if trigger_job is not None
            else detect_runtime_client()
        )
        auth_status = background_status(config, client=resolved_host_client)
        execution_client = resolved_host_client or auth_status.selected_cli or "unknown"
        if not auth_status.ready:
            from harness_mem.autonomous.worker import (
                record_post_turn_preflight_failure,
            )
            from harness_mem.hook_background import background_generation_from_env

            if auth_status.reason == "disabled":
                message = "Hook-started Dream needs distill.autonomous.enabled=true."
            elif auth_status.reason == "unsupported_cli":
                message = (
                    f"No background CLI is implemented for '{auth_status.selected_cli}'."
                )
            elif auth_status.reason == "host_not_detected":
                message = "The current Agent host could not be identified."
            else:
                message = (
                    f"The selected background CLI '{auth_status.selected_cli}' was not found."
                )
            record_post_turn_preflight_failure(
                backend.data_dir,
                project_name=project_name,
                project_root=project_root,
                trigger_id=trigger_id,
                client=execution_client,
                dispatch_generation=background_generation_from_env(),
                error={"kind": "setup_required", "message": message},
            )
            return await _record_dream_tick(
                backend,
                project_name=project_name,
                source=source,
                trigger_id=trigger_id,
                payload={
                    "success": False,
                    "status": "failed",
                    "project_name": project_name,
                    "reason": f"{message} The session job remains queued.",
                    "session_distill": {
                        "job_id": trigger_job_id,
                        "state": "setup_required",
                    },
                },
            )
        from harness_mem.autonomous.worker import run_autonomous_distill_batch
        from harness_mem.hook_background import background_generation_from_env

        hook_session = await asyncio.to_thread(
            run_autonomous_distill_batch,
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            trigger_id=trigger_id,
            client=execution_client,
            provider=None,
            max_jobs=1,
            preferred_job_id=trigger_job_id,
            launch_source="ide_hook",
            dispatch_generation=background_generation_from_env(),
        )
        if not hook_session.get("success", False):
            return await _record_dream_tick(
                backend,
                project_name=project_name,
                source=source,
                trigger_id=trigger_id,
                payload={
                    "success": False,
                    "status": "failed",
                    "project_name": project_name,
                    "reason": str(
                        hook_session.get("reason")
                        or hook_session.get("state")
                        or "hook session distill failed"
                    ),
                    "session_distill": _dream_session_receipt(
                        hook_session, trigger_job_id
                    ),
                },
            )

    decision = await dream_scheduler_decision(
        backend,
        project_name=project_name,
        config=config,
    )
    force_for_hook_session = hook_session is not None
    if not decision.eligible and not force_for_hook_session:
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": True,
                "status": "skipped",
                "project_name": project_name,
                "reason": decision.reason,
                "last_run_id": decision.last_run_id,
                "next_eligible_at": _iso(decision.next_eligible_at),
            },
        )

    started_at = _now()
    job = ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        kind="dream",
        phase="metabolism",
        status="processing",
        source=source,
        input_refs=[
            value
            for value in (decision.last_run_id, trigger_job_id)
            if value
        ],
        created_at=started_at,
        updated_at=started_at,
    )
    stale_before = started_at - timedelta(
        seconds=max(1, config.dream_auto_max_runtime_seconds)
    )
    active_job = backend.reflection_job_store.save_if_no_active_processing(
        job,
        stale_before=stale_before,
    )
    if active_job is not None:
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": True,
                "status": "skipped",
                "project_name": project_name,
                "reason": "dream job already processing",
                "job_id": active_job.id,
            },
        )
    # Another process may have completed a very short Dream between our first
    # gate decision and this transaction. Re-check after winning the durable
    # claim so a stale eligible decision cannot launch a duplicate run.
    confirmed_decision = await dream_scheduler_decision(
        backend,
        project_name=project_name,
        config=config,
    )
    if not confirmed_decision.eligible and not force_for_hook_session:
        job.phase = "done"
        job.status = "completed"
        job.completed_at = _now()
        backend.reflection_job_store.save(job)
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": True,
                "status": "skipped",
                "project_name": project_name,
                "reason": confirmed_decision.reason,
                "job_id": job.id,
                "last_run_id": confirmed_decision.last_run_id,
                "next_eligible_at": _iso(confirmed_decision.next_eligible_at),
            },
        )
    try:
        selected_provider = _dream_provider_from_config(config, host_client=host_client)
        run = await _run_dream_with_progress_timeout(
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            source=source,
            reflection_job_id=job.id,
            timeout_seconds=config.dream_auto_max_runtime_seconds,
            semantic_provider=selected_provider,
            host_client=host_client,
        )
        if hook_session is not None:
            run.notes = list(run.notes or [])
            run.notes.append(
                "Hook session distill "
                f"{_dream_session_receipt(hook_session, trigger_job_id)['state']}: "
                f"{trigger_job_id}"
            )
            await cast(LocalStructuredStore, backend.structured_store).save_dream_run(
                run
            )
        job.phase = "done"
        job.status = "completed" if run.status == "completed" else "failed"
        job.output_candidate_ids = [item.source_id for item in run.items]
        job.completed_at = run.completed_at
        if run.status == "failed":
            job.error = "dream: one or more dream items failed"
        backend.reflection_job_store.save(job)
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": run.status == "completed",
                "status": run.status,
                "project_name": project_name,
                "job_id": job.id,
                "run_id": run.id,
                "summary": run.handling_summary,
                "session_distill": (
                    _dream_session_receipt(hook_session, trigger_job_id)
                    if hook_session is not None
                    else None
                ),
            },
        )
    except Exception as exc:
        job.phase = "done"
        job.status = "failed"
        job.error = f"dream: {type(exc).__name__}: {exc}"
        job.completed_at = _now()
        backend.reflection_job_store.save(job)
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": False,
                "status": "failed",
                "project_name": project_name,
                "job_id": job.id,
                "error": str(exc) or exc.__class__.__name__,
            },
        )


def _latest_dream_tick_receipt(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
) -> dict[str, Any] | None:
    receipts = _dream_tick_receipts(backend, project_name=project_name, limit=1)
    return receipts[-1] if receipts else None


def _dream_tick_receipts(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    path = backend.data_dir / "events.log"
    events: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(candidate, dict):
                    continue
                if (
                    candidate.get("type") == EventType.COMMAND_INVOKED.value
                    and candidate.get("command") == "dream.auto_tick"
                    and candidate.get("project_name") == project_name
                ):
                    events.append(candidate)
    except OSError:
        return []
    receipts: list[dict[str, Any]] = []
    for event in events[-max(1, limit) :]:
        extra_value = event.get("extra")
        extra = extra_value if isinstance(extra_value, dict) else {}
        receipts.append(
            {
                "timestamp": event.get("timestamp"),
                "status": extra.get("status"),
                "reason": extra.get("reason"),
                "source": extra.get("source"),
                "trigger_id": extra.get("trigger_id"),
                "job_id": extra.get("job_id"),
                "run_id": extra.get("run_id"),
                "last_run_id": extra.get("last_run_id"),
                "next_eligible_at": extra.get("next_eligible_at"),
                "receipt_state": "recorded",
            }
        )
    return receipts


async def _record_dream_tick(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    source: DreamSource,
    trigger_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist one content-free auto-tick receipt without failing maintenance."""

    receipt = {
        "status": payload.get("status"),
        "reason": payload.get("reason") or payload.get("error"),
        "source": source,
        "trigger_id": trigger_id,
        "job_id": payload.get("job_id"),
        "run_id": payload.get("run_id"),
        "last_run_id": payload.get("last_run_id"),
        "next_eligible_at": payload.get("next_eligible_at"),
    }
    result = dict(payload)
    try:
        await get_event_logger(backend.data_dir).log(
            EventType.COMMAND_INVOKED,
            project_name=project_name,
            command="dream.auto_tick",
            extra=receipt,
        )
        result["tick_receipt"] = {"state": "recorded"}
    except Exception as exc:  # noqa: BLE001 - observability must fail open.
        result["tick_receipt"] = {
            "state": "degraded",
            "reason": f"{type(exc).__name__}: {exc}"[:512],
        }
    return result


async def _run_dream_with_progress_timeout(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None,
    config: MergedConfig,
    source: DreamSource,
    reflection_job_id: str,
    timeout_seconds: int,
    semantic_provider: Any | None = None,
    host_client: str | None = None,
) -> DreamRun:
    seconds = max(1, timeout_seconds)
    deadline = _now() + timedelta(seconds=seconds)
    try:
        return await asyncio.wait_for(
            dream_once(
                backend,
                project_name=project_name,
                project_root=project_root,
                config=config,
                source=source,
                reflection_job_id=reflection_job_id,
                deadline=deadline,
                semantic_provider=semantic_provider,
                host_client=host_client,
            ),
            timeout=seconds,
        )
    except TimeoutError:
        store = cast(LocalStructuredStore, backend.structured_store)
        runs = await store.list_dream_runs(project_name, limit=20)
        run = next(
            (
                item
                for item in runs
                if item.reflection_job_id == reflection_job_id
                and item.status == "processing"
            ),
            None,
        )
        if run is not None:
            completed_at = _now()
            run.status = "failed"
            run.completed_at = completed_at
            run.duration_ms = int(
                (completed_at - run.started_at).total_seconds() * 1000
            )
            run.notes = list(run.notes or [])
            run.notes.append("dream runtime exceeded max_runtime_seconds")
            await store.save_dream_run(run)
        raise TimeoutError("dream runtime exceeded max_runtime_seconds") from None


def _dream_session_receipt(
    payload: dict[str, Any],
    job_id: str | None,
) -> dict[str, Any]:
    outcomes = [
        item
        for item in payload.get("outcomes", [])
        if isinstance(item, dict)
    ]
    completed = sum(item.get("status") == "completed" for item in outcomes)
    return {
        "job_id": job_id,
        "state": str(payload.get("state") or "unknown"),
        "completed": completed,
        "provider": str(
            next(
                (
                    item.get("provider", {}).get("name")
                    for item in outcomes
                    if isinstance(item.get("provider"), dict)
                    and item.get("provider", {}).get("name")
                ),
                "",
            )
            or ""
        ),
    }


async def cmd_dream(
    project_name: str,
    *,
    action: Literal["ledger", "run", "auto-tick"] = "ledger",
    project_root: str | None = None,
    run_id: str | None = None,
    config: MergedConfig | None = None,
) -> int:
    from harness_mem.commands.support import DEFAULT_DATA_DIR, find_project_root
    from harness_mem.config.merge import load_merged_config

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        resolved_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else find_project_root(project_name)
        )
        root = str(resolved_root) if resolved_root is not None else None
        merged = config or (
            load_merged_config(root) if root is not None else MergedConfig()
        )
        if action == "run":
            run = await dream_once(
                backend,
                project_name=project_name,
                project_root=root,
                config=merged,
                source="agent",
            )
            print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if action == "auto-tick":
            if root is None:
                print(f"project root is required for automatic Dream: {project_name}")
                return 1
            payload = await dream_auto_tick(
                backend,
                project_name=project_name,
                project_root=root,
                config=merged,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload.get("success") else 1
        payload = await latest_dream_ledger(
            backend,
            project_name=project_name,
            run_id=run_id,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        await backend.close()
