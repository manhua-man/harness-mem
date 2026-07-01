"""v3.1 Auto Dream Memory Maintenance business command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

from harness_mem.commands.metabolism_pass import select_metabolism_pass
from harness_mem.commands.replay_window import ReplayBudget, ReplayWindow
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import DreamItem, DreamRun, MemoryEntry, ReflectionJob
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


DreamSource = Literal["user", "agent", "ide_hook", "scheduler"]
POLICY_VERSION = "v3.1"


@dataclass(frozen=True)
class DreamSchedulerDecision:
    eligible: bool
    reason: str
    last_run_id: str | None = None
    next_eligible_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dream_handle_config(
    config: MergedConfig | dict[str, Any] | None,
) -> dict[str, Any]:
    cfg = config.to_reflection_config() if isinstance(config, MergedConfig) else (config or {})
    dream_cfg = cfg.get("dream", {}) if isinstance(cfg, dict) else {}
    handle_cfg = dream_cfg.get("handle", {}) if isinstance(dream_cfg, dict) else {}
    return handle_cfg if isinstance(handle_cfg, dict) else {}


def _replay_window_to_input_window(window: ReplayWindow) -> dict[str, Any]:
    dimensions: dict[str, dict[str, Any]] = {}
    for name, dim in window.dimensions.items():
        dimensions[name] = {
            "selected_ids": list(dim.selected_ids),
            "truncated": dim.truncated,
            "total_seen": dim.total_seen,
        }
    return {
        "time_range": {
            "start": window.time_range[0].isoformat(),
            "end": window.time_range[1].isoformat(),
        },
        "dimensions": dimensions,
        "signal_ids": list(window.signal_ids),
        "notes": list(window.notes),
    }


def _truth_type_for_kind(kind: str) -> str:
    if kind == "memory_entry":
        return "memory_entry"
    if kind == "confirmed_rule":
        return "confirmed_rule"
    if kind == "relation_fact":
        return "relation_fact"
    raise ValueError(f"unsupported truth kind: {kind}")


async def _truth_payload(
    store: LocalStructuredStore,
    truth_kind: str,
    truth_id: str,
) -> dict[str, Any] | None:
    if truth_kind == "memory_entry":
        memory_entry = await store.get_memory_entry(truth_id)
        return memory_entry.to_dict() if memory_entry is not None else None
    if truth_kind == "confirmed_rule":
        confirmed_rule = await store.get_confirmed_rule(truth_id)
        return confirmed_rule.to_dict() if confirmed_rule is not None else None
    if truth_kind == "relation_fact":
        relation_fact = await store.get_relation_fact(truth_id)
        return relation_fact.to_dict() if relation_fact is not None else None
    return None


def _truth_text(payload: dict[str, Any], truth_kind: str) -> str:
    if truth_kind == "memory_entry":
        return str(payload.get("content") or "")
    if truth_kind == "confirmed_rule":
        trigger = str(payload.get("trigger") or "").strip()
        pattern = str(payload.get("pattern") or "").strip()
        return f"When {trigger}: {pattern}".strip()
    if truth_kind == "relation_fact":
        return str(payload.get("evidence") or "")
    return ""


async def _restore_truth_snapshots(
    store: LocalStructuredStore,
    snapshots: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for snapshot in snapshots:
        truth_type = snapshot["truth_type"]
        truth_id = snapshot["truth_id"]
        before = snapshot["before"]
        collection = store._truth_collection_for_type(truth_type)
        ok = await store._persist_truth_snapshot(collection, truth_id, before)
        if not ok:
            failures.append(f"restore failed for {truth_type}:{truth_id}")
    return failures


async def _mark_truth_historical(
    store: LocalStructuredStore,
    *,
    truth_kind: str,
    truth_id: str,
    valid_to: datetime,
    superseded_by: str | None = None,
) -> bool:
    return await store._update_truth_supersede_fields(
        _truth_type_for_kind(truth_kind),
        truth_id,
        valid_to=valid_to,
        add_superseded_by=superseded_by,
    )


async def _apply_merge(
    store: LocalStructuredStore,
    candidate: MergeSuggestionCandidate,
    *,
    run_id: str,
    now: datetime,
) -> DreamItem:
    before_a = await _truth_payload(store, candidate.target_a_kind, candidate.target_a_id)
    before_b = await _truth_payload(store, candidate.target_b_kind, candidate.target_b_id)
    if before_a is None or before_b is None:
        await store.update_merge_suggestion_candidate_status(candidate.id, "rejected")
        return DreamItem(
            source_kind="merge_suggestion",
            source_id=candidate.id,
            evidence_ids=list(candidate.evidence_signal_ids),
            risk="high",
            proposed_action="merge",
            final_action="failed",
            reason="merge target missing; candidate rejected to avoid pending review",
            result={"candidate_status": "rejected"},
            error="missing merge target",
        )

    merged_content = candidate.proposed_content.strip()
    if not merged_content:
        text_a = _truth_text(before_a, candidate.target_a_kind)
        text_b = _truth_text(before_b, candidate.target_b_kind)
        merged_content = "\n".join(
            part for part in (text_a, text_b) if part.strip()
        ).strip()
    if not merged_content:
        await store.update_merge_suggestion_candidate_status(candidate.id, "rejected")
        return DreamItem(
            source_kind="merge_suggestion",
            source_id=candidate.id,
            evidence_ids=list(candidate.evidence_signal_ids),
            risk="high",
            proposed_action="merge",
            final_action="archived",
            reason="merge lacked usable content; archived as dream-only record",
            result={"candidate_status": "rejected"},
        )

    merged_entry = MemoryEntry(
        project_name=candidate.project_name,
        category="decision",
        content=merged_content,
        source=f"dream:{run_id}",
        confidence=max(0.7, min(1.0, candidate.similarity_score)),
        status="user_confirmed",
        tags=["dream-merge"],
        provenance={
            "dream_run_id": run_id,
            "candidate_id": candidate.id,
            "source_truth_ids": [candidate.target_a_id, candidate.target_b_id],
            "policy_version": POLICY_VERSION,
        },
        memory_type="semantic",
        created_at=now,
        updated_at=now,
        valid_from=now,
        recorded_at=now,
        supersedes=[candidate.target_a_id, candidate.target_b_id],
    )
    await store.save_memory_entry(merged_entry)

    ok_a = await _mark_truth_historical(
        store,
        truth_kind=candidate.target_a_kind,
        truth_id=candidate.target_a_id,
        valid_to=now,
        superseded_by=merged_entry.id,
    )
    ok_b = await _mark_truth_historical(
        store,
        truth_kind=candidate.target_b_kind,
        truth_id=candidate.target_b_id,
        valid_to=now,
        superseded_by=merged_entry.id,
    )
    if not (ok_a and ok_b):
        await _restore_truth_snapshots(
            store,
            [
                {
                    "truth_type": _truth_type_for_kind(candidate.target_a_kind),
                    "truth_id": candidate.target_a_id,
                    "before": before_a,
                },
                {
                    "truth_type": _truth_type_for_kind(candidate.target_b_kind),
                    "truth_id": candidate.target_b_id,
                    "before": before_b,
                },
            ],
        )
        await store.soft_delete_memory_entry(merged_entry.id)
        await store.update_merge_suggestion_candidate_status(candidate.id, "rejected")
        return DreamItem(
            source_kind="merge_suggestion",
            source_id=candidate.id,
            evidence_ids=list(candidate.evidence_signal_ids),
            risk="high",
            proposed_action="merge",
            final_action="failed",
            reason="merge failed while marking source truths historical",
            result={"candidate_status": "rejected", "created_entry_id": merged_entry.id},
            error="failed to mark source truths historical",
        )

    await store.update_merge_suggestion_candidate_status(
        candidate.id, "user_confirmed"
    )
    return DreamItem(
        source_kind="merge_suggestion",
        source_id=candidate.id,
        evidence_ids=list(candidate.evidence_signal_ids),
        risk="medium",
        proposed_action="merge",
        final_action="applied",
        reason="auto-applied merge; source truths marked historical, merged entry created",
        undo={
            "kind": "merge",
            "created_truths": [{"truth_type": "memory_entry", "truth_id": merged_entry.id}],
            "restore_truth_snapshots": [
                {
                    "truth_type": _truth_type_for_kind(candidate.target_a_kind),
                    "truth_id": candidate.target_a_id,
                    "before": before_a,
                },
                {
                    "truth_type": _truth_type_for_kind(candidate.target_b_kind),
                    "truth_id": candidate.target_b_id,
                    "before": before_b,
                },
            ],
            "candidate_id": candidate.id,
        },
        result={
            "candidate_status": "user_confirmed",
            "created_entry_id": merged_entry.id,
        },
    )


async def _apply_stale(
    store: LocalStructuredStore,
    candidate: StaleTruthSuggestionCandidate,
    *,
    now: datetime,
) -> DreamItem:
    before = await _truth_payload(store, candidate.target_kind, candidate.target_id)
    if before is None:
        await store.update_stale_truth_suggestion_candidate_status(candidate.id, "rejected")
        return DreamItem(
            source_kind="stale_truth_suggestion",
            source_id=candidate.id,
            evidence_ids=list(candidate.evidence_signal_ids),
            risk="medium",
            proposed_action="mark_stale",
            final_action="failed",
            reason="stale target missing; candidate rejected to avoid pending review",
            result={"candidate_status": "rejected"},
            error="missing stale target",
        )
    ok = await _mark_truth_historical(
        store,
        truth_kind=candidate.target_kind,
        truth_id=candidate.target_id,
        valid_to=now,
    )
    if not ok:
        await store.update_stale_truth_suggestion_candidate_status(candidate.id, "rejected")
        return DreamItem(
            source_kind="stale_truth_suggestion",
            source_id=candidate.id,
            evidence_ids=list(candidate.evidence_signal_ids),
            risk="medium",
            proposed_action="mark_stale",
            final_action="failed",
            reason="failed to mark stale target historical",
            result={"candidate_status": "rejected"},
            error="truth update failed",
        )
    await store.update_stale_truth_suggestion_candidate_status(
        candidate.id, "user_confirmed"
    )
    return DreamItem(
        source_kind="stale_truth_suggestion",
        source_id=candidate.id,
        evidence_ids=list(candidate.evidence_signal_ids),
        risk="low",
        proposed_action="mark_stale",
        final_action="applied",
        reason="auto-marked long-silent truth historical; no hard delete",
        undo={
            "kind": "mark_stale",
            "restore_truth_snapshots": [
                {
                    "truth_type": _truth_type_for_kind(candidate.target_kind),
                    "truth_id": candidate.target_id,
                    "before": before,
                }
            ],
            "candidate_id": candidate.id,
        },
        result={
            "candidate_status": "user_confirmed",
            "target_id": candidate.target_id,
        },
    )


async def _queue_supersede_for_review(
    store: LocalStructuredStore,
    candidate: SupersedeCandidate,
    *,
    auto_apply_requested: bool,
) -> DreamItem:
    existing = await store.get_supersede_candidate(candidate.id)
    if existing is None:
        await store.save_supersede_candidate(candidate)
        existing = await store.get_supersede_candidate(candidate.id)
    if existing is None:
        return DreamItem(
            source_kind="supersede",
            source_id=candidate.id,
            evidence_ids=[candidate.evidence] if candidate.evidence else [],
            risk="high",
            proposed_action="supersede",
            final_action="failed",
            reason="supersede candidate could not be saved for explicit review",
            result={"candidate_status": "missing"},
            error="save_supersede_candidate returned no readable candidate",
        )
    return DreamItem(
        source_kind="supersede",
        source_id=candidate.id,
        evidence_ids=[candidate.evidence] if candidate.evidence else [],
        risk="high",
        proposed_action="supersede",
        final_action="pending_review",
        reason=(
            "queued supersede candidate for explicit review; dream does not "
            "mutate truth lineage"
        ),
        result={
            "candidate_status": existing.status,
            "target_id": candidate.target_id,
            "replacement_id": candidate.replacement_id,
            "review_tools": ["confirm_supersede", "reject_supersede"],
            "auto_apply_requested": auto_apply_requested,
        },
    )


async def _reject_or_archive(
    store: LocalStructuredStore,
    *,
    source_kind: str,
    source_id: str,
    evidence_ids: list[str] | None = None,
    proposed_action: str,
    reason: str,
    final_action: Literal["rejected", "archived"],
) -> DreamItem:
    if source_kind == "merge_suggestion":
        await store.update_merge_suggestion_candidate_status(source_id, "rejected")
    elif source_kind == "stale_truth_suggestion":
        await store.update_stale_truth_suggestion_candidate_status(source_id, "rejected")
    elif source_kind == "supersede":
        await store.update_supersede_candidate_status(
            source_id,
            "rejected",
            reviewer_id="dream",
        )
    return DreamItem(
        source_kind=source_kind,
        source_id=source_id,
        evidence_ids=list(evidence_ids or []),
        risk="medium",
        proposed_action=cast(Any, proposed_action),
        final_action=final_action,
        reason=reason,
        result={"candidate_status": "rejected"},
    )


async def dream_once(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    config: MergedConfig | dict[str, Any] | None = None,
    source: DreamSource = "agent",
    reflection_job_id: str | None = None,
    budget: ReplayBudget | None = None,
    deadline: datetime | None = None,
) -> DreamRun:
    """Run one v3.1 dream maintenance pass and persist a DreamRun ledger."""
    store = cast(LocalStructuredStore, backend.structured_store)
    handle_cfg = _dream_handle_config(config)
    started_at = _now()
    notes: list[str] = []
    items: list[DreamItem] = []

    normalized_budget = budget or ReplayBudget()
    pass_result = await select_metabolism_pass(
        backend,
        project_name=project_name,
        budget=normalized_budget,
    )

    input_window = _replay_window_to_input_window(pass_result.window)
    selected_signal_ids = list(pass_result.window.signal_ids)
    notes.extend(pass_result.window.notes)
    notes.extend(pass_result.notes)

    run_stub = DreamRun(
        project_name=project_name,
        started_at=started_at,
        completed_at=None,
        status="processing",
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        input_window=input_window,
        selected_signal_ids=selected_signal_ids,
        items=[],
        notes=notes if notes else None,
    )
    await store.save_dream_run(run_stub)

    async def persist_progress(*, check_deadline: bool = True) -> None:
        run_stub.items = list(items)
        run_stub.handling_summary = {}
        run_stub.model_post_init(None)
        if check_deadline and deadline is not None and _now() >= deadline:
            completed_at = _now()
            run_stub.status = "failed"
            run_stub.completed_at = completed_at
            run_stub.duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            run_stub.notes = list(run_stub.notes or [])
            run_stub.notes.append("dream runtime exceeded max_runtime_seconds")
            await store.save_dream_run(run_stub)
            raise TimeoutError("dream runtime exceeded max_runtime_seconds")
        await store.save_dream_run(run_stub)

    pending_merges = await store.list_merge_suggestion_candidates(project_name, status="pending")
    pending_stale = await store.list_stale_truth_suggestion_candidates(project_name, status="pending")
    pending_supersedes = await store.list_supersede_candidates(project_name, status="pending")
    await persist_progress()

    seen_ids: set[str] = set()
    merge_candidates: list[MergeSuggestionCandidate] = []
    for merge_candidate in [*pending_merges, *pass_result.merge]:
        if merge_candidate.id in seen_ids:
            continue
        seen_ids.add(merge_candidate.id)
        if merge_candidate.metabolism_run_id == "pending":
            merge_candidate.metabolism_run_id = run_stub.id
            await store.save_merge_suggestion_candidate(merge_candidate)
        merge_candidates.append(merge_candidate)

    seen_ids.clear()
    stale_candidates: list[StaleTruthSuggestionCandidate] = []
    for stale_candidate in [*pending_stale, *pass_result.stale]:
        if stale_candidate.id in seen_ids:
            continue
        seen_ids.add(stale_candidate.id)
        if stale_candidate.metabolism_run_id == "pending":
            stale_candidate.metabolism_run_id = run_stub.id
            await store.save_stale_truth_suggestion_candidate(stale_candidate)
        stale_candidates.append(stale_candidate)

    seen_ids.clear()
    supersede_candidates: list[SupersedeCandidate] = []
    for supersede_candidate in [*pending_supersedes, *pass_result.supersede]:
        if supersede_candidate.id in seen_ids:
            continue
        seen_ids.add(supersede_candidate.id)
        if supersede_candidate.status == "pending" and supersede_candidate.id not in {
            pending.id for pending in pending_supersedes
        }:
            await store.save_supersede_candidate(supersede_candidate)
        supersede_candidates.append(supersede_candidate)

    for merge_candidate in merge_candidates:
        await persist_progress()
        if not handle_cfg.get("allow_merge", True) or not handle_cfg.get("auto_apply", True):
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="merge_suggestion",
                    source_id=merge_candidate.id,
                    evidence_ids=list(merge_candidate.evidence_signal_ids),
                    proposed_action="merge",
                    final_action="archived",
                    reason="merge disabled by dream policy; archived as dream-only record",
                )
            )
        else:
            items.append(await _apply_merge(store, merge_candidate, run_id=run_stub.id, now=started_at))
        await persist_progress()

    for stale_candidate in stale_candidates:
        await persist_progress()
        if not handle_cfg.get("allow_mark_stale", True) or not handle_cfg.get("auto_apply", True):
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="stale_truth_suggestion",
                    source_id=stale_candidate.id,
                    evidence_ids=list(stale_candidate.evidence_signal_ids),
                    proposed_action="mark_stale",
                    final_action="archived",
                    reason="stale marking disabled by dream policy; archived as dream-only record",
                )
            )
        else:
            items.append(await _apply_stale(store, stale_candidate, now=started_at))
        await persist_progress()

    for supersede_candidate in supersede_candidates:
        await persist_progress()
        if not handle_cfg.get("allow_supersede", True):
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="supersede",
                    source_id=supersede_candidate.id,
                    evidence_ids=[supersede_candidate.evidence] if supersede_candidate.evidence else [],
                    proposed_action="supersede",
                    final_action="archived",
                    reason="supersede disabled by dream policy; archived as dream-only record",
                )
            )
        else:
            items.append(
                await _queue_supersede_for_review(
                    store,
                    supersede_candidate,
                    auto_apply_requested=bool(handle_cfg.get("auto_apply", True)),
                )
            )
        await persist_progress()

    completed_at = _now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    status: Literal["completed", "failed"] = (
        "failed" if any(item.final_action == "failed" for item in items) else "completed"
    )
    run = DreamRun(
        id=run_stub.id,
        project_name=project_name,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        input_window=input_window,
        selected_signal_ids=selected_signal_ids,
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
    if run is None:
        return {"success": True, "project_name": project_name, "run": None}
    return {"success": True, "project_name": project_name, "run": run.to_dict()}


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

    payload: dict[str, Any] = {
        "enabled": bool(config.dream_auto_enabled) if config is not None else False,
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


async def undo_dream_item(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    run_id: str,
    item_id: str,
) -> dict[str, Any]:
    store = cast(LocalStructuredStore, backend.structured_store)
    run = await store.get_dream_run(run_id)
    if run is None or run.project_name != project_name:
        return {"success": False, "error": f"DreamRun not found: {run_id}"}
    item = next((candidate for candidate in run.items if candidate.id == item_id), None)
    if item is None:
        return {"success": False, "error": f"DreamItem not found: {item_id}"}
    undo = item.undo or {}
    if item.result.get("undone_at"):
        return {"success": True, "status": "already_undone", "item": item.to_dict()}

    restore_snapshots = list(undo.get("restore_truth_snapshots") or [])
    failures = await _restore_truth_snapshots(store, restore_snapshots)

    for created in undo.get("created_truths") or []:
        if created.get("truth_type") == "memory_entry":
            ok = await store.soft_delete_memory_entry(created["truth_id"])
            if not ok:
                failures.append(f"soft-delete failed for memory_entry:{created['truth_id']}")

    if failures:
        return {
            "success": False,
            "status": "failed",
            "error": "; ".join(failures),
            "item": item.to_dict(),
        }

    item.result["undone_at"] = _now().isoformat()
    await store.save_dream_run(run)
    return {"success": True, "status": "undone", "item": item.to_dict()}


async def _latest_project_activity(
    backend: LocalMemoryBackend,
    project_name: str,
) -> datetime | None:
    latest: datetime | None = None
    observations = await backend.verbatim_store.list(limit=10000)
    for observation in observations:
        if observation.metadata.get("project_name") != project_name:
            continue
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
    interval_elapsed = last_run is None or now - last_run.started_at >= min_interval
    idle_elapsed = now - latest_activity >= timedelta(seconds=config.dream_auto_idle_seconds)
    if config.dream_auto_trigger == "interval":
        eligible = interval_elapsed
    elif config.dream_auto_trigger == "idle":
        eligible = idle_elapsed
    else:
        eligible = interval_elapsed or idle_elapsed

    next_eligible_at = None
    if last_run is not None:
        next_eligible_at = last_run.started_at + min_interval
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
) -> dict[str, Any]:
    decision = await dream_scheduler_decision(
        backend,
        project_name=project_name,
        config=config,
    )
    if not decision.eligible:
        return {
            "success": True,
            "status": "skipped",
            "project_name": project_name,
            "reason": decision.reason,
            "last_run_id": decision.last_run_id,
            "next_eligible_at": _iso(decision.next_eligible_at),
        }

    started_at = _now()
    job = ReflectionJob(
        project_name=project_name,
        project_root=project_root,
        kind="dream",
        phase="metabolism",
        status="processing",
        source=source,
        input_refs=[decision.last_run_id] if decision.last_run_id else [],
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
        return {
            "success": True,
            "status": "skipped",
            "project_name": project_name,
            "reason": "dream job already processing",
            "job_id": active_job.id,
        }
    try:
        run = await _run_dream_with_progress_timeout(
            backend,
            project_name=project_name,
            config=config,
            source=source,
            reflection_job_id=job.id,
            timeout_seconds=config.dream_auto_max_runtime_seconds,
        )
        job.phase = "done"
        job.status = "completed" if run.status == "completed" else "failed"
        job.output_candidate_ids = [item.source_id for item in run.items]
        job.completed_at = run.completed_at
        if run.status == "failed":
            job.error = "dream: one or more dream items failed"
        backend.reflection_job_store.save(job)
        return {
            "success": True,
            "status": "completed",
            "project_name": project_name,
            "job_id": job.id,
            "run_id": run.id,
            "summary": run.handling_summary,
        }
    except Exception as exc:
        job.phase = "done"
        job.status = "failed"
        job.error = f"dream: {type(exc).__name__}: {exc}"
        job.completed_at = _now()
        backend.reflection_job_store.save(job)
        return {
            "success": False,
            "status": "failed",
            "project_name": project_name,
            "job_id": job.id,
            "error": str(exc) or exc.__class__.__name__,
        }


async def _run_dream_with_progress_timeout(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    config: MergedConfig,
    source: DreamSource,
    reflection_job_id: str,
    timeout_seconds: int,
) -> DreamRun:
    deadline = _now() + timedelta(seconds=max(1, timeout_seconds))
    return await dream_once(
        backend,
        project_name=project_name,
        config=config,
        source=source,
        reflection_job_id=reflection_job_id,
        deadline=deadline,
    )


async def cmd_dream(
    project_name: str,
    *,
    action: Literal["ledger", "run", "auto-tick", "undo"] = "ledger",
    project_root: str | None = None,
    run_id: str | None = None,
    item_id: str | None = None,
    config: MergedConfig | None = None,
) -> int:
    from harness_mem.commands.support import DEFAULT_DATA_DIR
    from harness_mem.config.merge import load_merged_config

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        root = project_root or str(Path.cwd())
        merged = config or load_merged_config(root)
        if action == "run":
            run = await dream_once(
                backend,
                project_name=project_name,
                config=merged,
                source="agent",
            )
            print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if action == "auto-tick":
            payload = await dream_auto_tick(
                backend,
                project_name=project_name,
                project_root=root,
                config=merged,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload.get("success") else 1
        if action == "undo":
            if run_id is None or item_id is None:
                print("dream undo requires --run-id and --item-id")
                return 1
            payload = await undo_dream_item(
                backend,
                project_name=project_name,
                run_id=run_id,
                item_id=item_id,
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
