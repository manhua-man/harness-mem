"""v3.1 Auto Dream Memory Maintenance business command."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from harness_mem.commands.metabolism_pass import select_metabolism_pass
from harness_mem.commands.replay_window import ReplayBudget, ReplayWindow
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
    MemoryEntry,
    ReflectionJob,
)
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.event_log import EventType, get_event_logger
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


@dataclass(frozen=True)
class DreamRecheckSignal:
    """One non-persisted maintenance hypothesis about current knowledge."""

    kind: Literal["duplicate", "conflict", "stale", "feedback"]
    target_ids: tuple[str, ...]
    proposed_action: Literal["merge", "mark_stale", "supersede"]
    risk: Literal["medium", "high"]
    reason: str
    cause_id: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dream_handle_config(
    config: MergedConfig | dict[str, Any] | None,
) -> dict[str, Any]:
    cfg = (
        config.to_reflection_config()
        if isinstance(config, MergedConfig)
        else (config or {})
    )
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
    before_a = await _truth_payload(
        store, candidate.target_a_kind, candidate.target_a_id
    )
    before_b = await _truth_payload(
        store, candidate.target_b_kind, candidate.target_b_id
    )
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
            result={
                "candidate_status": "rejected",
                "created_entry_id": merged_entry.id,
            },
            error="failed to mark source truths historical",
        )

    await store.update_merge_suggestion_candidate_status(candidate.id, "user_confirmed")
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
            "created_truths": [
                {"truth_type": "memory_entry", "truth_id": merged_entry.id}
            ],
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
        await store.update_stale_truth_suggestion_candidate_status(
            candidate.id, "rejected"
        )
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
        await store.update_stale_truth_suggestion_candidate_status(
            candidate.id, "rejected"
        )
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


async def _detect_separated_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None,
) -> list[DreamRecheckSignal]:
    """Find recheck hypotheses without creating candidate/evidence rows.

    Dream signals are not candidate facts. A single-entry signal may proceed
    through source reopening and trusted confirmation; a multi-entry signal is
    retained only in the immutable Dream ledger until a comparative executor is
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
                    proposed_action="supersede",
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
                    proposed_action="mark_stale",
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
                proposed_action="mark_stale",
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
    from harness_mem.commands.support import _detected_runtime_client, normalize_client_name

    client = normalize_client_name(host_client or _detected_runtime_client())
    return build_semantic_executor(config, client)


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
                _archived_recheck_item(
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
                _archived_recheck_item(
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
                _archived_recheck_item(
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
            point for point in plan if point["disposition"] in {"reject", "refine", "supersede"}
        ]
        if blocked:
            return [
                _archived_recheck_item(
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


def _archived_recheck_item(
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
        final_action="archived",
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
            final_action="archived",
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
    mutation_id = outcome.get("mutation_id")
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
        undo=(
            {"kind": "knowledge_mutation", "mutation_id": str(mutation_id)}
            if mutation_id
            else {}
        ),
        result=result,
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
        await store.update_stale_truth_suggestion_candidate_status(
            source_id, "rejected"
        )
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
    project_root: str | Path | None = None,
    config: MergedConfig | dict[str, Any] | None = None,
    source: DreamSource = "agent",
    reflection_job_id: str | None = None,
    budget: ReplayBudget | None = None,
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
            budget=budget,
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
    budget: ReplayBudget | None = None,
    deadline: datetime | None = None,
    semantic_provider: Any | None = None,
    host_client: str | None = None,
    _run_id: str | None = None,
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
        id=_run_id or str(uuid4()),
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

    pending_merges = await store.list_merge_suggestion_candidates(
        project_name, status="pending"
    )
    pending_stale = await store.list_stale_truth_suggestion_candidates(
        project_name, status="pending"
    )
    pending_supersedes = await store.list_supersede_candidates(
        project_name, status="pending"
    )
    await persist_progress()

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
                    final_action="archived",
                    reason="Dream target is no longer current knowledge.",
                    result={"truth_change": "none"},
                )
            )
            continue
        if project_root is None:
            items.extend(
                _archived_recheck_item(
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
                allow_retire=bool(handle_cfg.get("allow_mark_stale", True)),
            )
        )
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
        if not handle_cfg.get("allow_merge", True):
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
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="merge_suggestion",
                    source_id=merge_candidate.id,
                    evidence_ids=list(merge_candidate.evidence_signal_ids),
                    proposed_action="merge",
                    final_action="archived",
                    reason=(
                        "Legacy merge suggestion was closed because it lacks the "
                        "source-backed comparative execution required for a truth change."
                    ),
                )
            )
        await persist_progress()

    for stale_candidate in stale_candidates:
        await persist_progress()
        if not handle_cfg.get("allow_mark_stale", True):
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
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="stale_truth_suggestion",
                    source_id=stale_candidate.id,
                    evidence_ids=list(stale_candidate.evidence_signal_ids),
                    proposed_action="mark_stale",
                    final_action="archived",
                    reason=(
                        "Legacy stale suggestion was closed because it lacks a "
                        "reopenable current source."
                    ),
                )
            )
        await persist_progress()

    for supersede_candidate in supersede_candidates:
        await persist_progress()
        if not handle_cfg.get("allow_supersede", True):
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="supersede",
                    source_id=supersede_candidate.id,
                    evidence_ids=[supersede_candidate.evidence]
                    if supersede_candidate.evidence
                    else [],
                    proposed_action="supersede",
                    final_action="archived",
                    reason="supersede disabled by dream policy; archived as dream-only record",
                )
            )
        else:
            items.append(
                await _reject_or_archive(
                    store,
                    source_kind="supersede",
                    source_id=supersede_candidate.id,
                    evidence_ids=[supersede_candidate.evidence]
                    if supersede_candidate.evidence
                    else [],
                    proposed_action="supersede",
                    final_action="archived",
                    reason=(
                        "Legacy supersede suggestion was closed because it lacks the "
                        "source-backed comparative execution required for a truth change."
                    ),
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

    mutation_id = str(undo.get("mutation_id") or "").strip()
    if mutation_id:
        try:
            await backend.structured_store.knowledge_store.undo_truth_mutation(
                mutation_id=mutation_id,
                reversal_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"dream-undo:{run.id}:{item.id}:{mutation_id}",
                    )
                ),
            )
        except ValueError as exc:
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "item": item.to_dict(),
            }
        item.result["undone_at"] = _now().isoformat()
        await store.save_dream_run(run)
        return {"success": True, "status": "undone", "item": item.to_dict()}

    restore_snapshots = list(undo.get("restore_truth_snapshots") or [])
    created_truths = list(undo.get("created_truths") or [])
    if not restore_snapshots and not created_truths:
        return {
            "success": False,
            "status": "not_reversible",
            "error": "Dream item has no reversible truth mutation",
            "item": item.to_dict(),
        }
    failures = await _restore_truth_snapshots(store, restore_snapshots)

    for created in created_truths:
        if created.get("truth_type") == "memory_entry":
            ok = await store.soft_delete_memory_entry(created["truth_id"])
            if not ok:
                failures.append(
                    f"soft-delete failed for memory_entry:{created['truth_id']}"
                )

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
    hook_session: dict[str, Any] | None = None
    if source == "ide_hook" and trigger_job_id:
        from harness_mem.commands.support import normalize_client_name

        auth_status = background_status(config, client=host_client)
        if not auth_status.ready:
            from harness_mem.autonomous.worker import (
                record_post_turn_preflight_failure,
            )
            from harness_mem.hook_background import background_generation_from_env

            if auth_status.reason == "disabled":
                message = "Hook-started Dream needs distill.autonomous.enabled=true."
            elif auth_status.reason == "legacy_restricted_off":
                message = "Background memory is off because of the legacy restricted setting."
            elif auth_status.reason == "unsupported_cli":
                message = (
                    f"No background CLI is implemented for '{auth_status.selected_cli}'."
                )
            else:
                message = (
                    f"The selected background CLI '{auth_status.selected_cli}' was not found."
                )
            record_post_turn_preflight_failure(
                backend.data_dir,
                project_name=project_name,
                project_root=project_root,
                trigger_id=trigger_id,
                client=normalize_client_name(host_client or "codex"),
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

        resolved_client = normalize_client_name(host_client or "codex")
        hook_session = await asyncio.to_thread(
            run_autonomous_distill_batch,
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            trigger_id=trigger_id,
            client=resolved_client,
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
    action: Literal["ledger", "run", "auto-tick", "undo"] = "ledger",
    project_root: str | None = None,
    run_id: str | None = None,
    item_id: str | None = None,
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
