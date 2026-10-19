"""v3.1 Auto Dream Memory Maintenance business command."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5
from urllib.parse import parse_qs, urlparse

from harness_mem.commands.evidence_admission import reopen_dream_knowledge_sources
from harness_mem.commands.dream_assimilation import (
    DreamAssimilationCandidate,
    apply_dream_assimilation,
    build_dream_maintenance_plan,
    prepare_dream_assimilation,
    dream_scope_text,
    dream_temporary_retirement_allowed,
)
from harness_mem.autonomous.models import (
    CandidateVerificationDecision,
    CandidateVerificationPoint,
    verification_scope_status,
)
from harness_mem.autonomous.authorization import background_on, background_status
from harness_mem.autonomous.provider import ProviderError
from harness_mem.config.merge import MergedConfig
from harness_mem.diagnostic_events import DiagnosticRun, diagnostic_parent_id, exception_locations
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


def _scope_fingerprint(entry: KnowledgeEntry) -> str:
    payload = {"title": entry.title, "statement": entry.statement,
               "module": list(entry.module_path),
               "report": entry.source_report.model_dump(mode="json") if entry.source_report else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


SOURCE_REVIEW_INTERVAL_DAYS = 30
DREAM_SOURCE_RECHECK_CONTRACT = "dream-source-recheck-v6"
_MISSING_SOURCE_REASONS = frozenset({
    "knowledge_source_missing", "knowledge_source_revision_missing",
    "knowledge_source_observation_missing", "knowledge_source_exchange_missing",
    "knowledge_source_chunk_missing", "repository_ref_missing",
})


def _source_review_due_at(review: dict[str, Any]) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(review["next_review_at"]))
        return value if value.tzinfo is not None else None
    except (KeyError, ValueError, TypeError):
        return None


async def _current_source_reviews(
    backend: LocalMemoryBackend, project_name: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Carry only reviews still bound to current content; no history side store."""
    entries = await backend.structured_store.knowledge_store.list_entries(project_name)
    fingerprints = {entry.id: _scope_fingerprint(entry) for entry in entries}
    runs = await backend.structured_store.list_dream_runs(project_name, limit=1)
    previous = runs[0].source_reviews if runs else {}
    reviews = {entry_id: dict(row) for entry_id, row in previous.items()
        if entry_id in fingerprints and row.get("policy_version") == "missing-source-review-v1"
        and row.get("fingerprint") == fingerprints[entry_id]
        and _source_review_due_at(row) is not None}
    return reviews, fingerprints


async def _scope_upgrade_coverage(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    """Reuse existing run receipts for scheduling only, never source admission."""
    prefix = "dream scope_partition_v3: "
    entries = await backend.structured_store.knowledge_store.list_entries(project_name)
    current = {entry.id: _scope_fingerprint(entry) for entry in entries}
    coverage: dict[str, Any] = {}
    for run in await backend.structured_store.list_dream_runs(project_name, limit=200):
        for note in run.notes or []:
            if not note.startswith(prefix):
                continue
            try:
                rows = json.loads(note[len(prefix):])
            except (ValueError, TypeError):
                continue
            if not isinstance(rows, dict):
                continue
            for entry_id, row in rows.items():
                if (entry_id in current and isinstance(row, dict)
                        and row.get("fingerprint") == current[entry_id]
                        and row.get("scope_status") == "source_scope_durable"
                        and row.get("semantic_support") == "supported"):
                    coverage.setdefault(entry_id, row)
    return coverage


async def _scope_recheck_attempt_times(
    backend: LocalMemoryBackend, project_name: str,
) -> dict[str, datetime]:
    """Rotate real source/model attempts without treating an attempt as acceptance."""
    attempted: dict[str, datetime] = {}
    for run in await backend.structured_store.list_dream_runs(project_name, limit=200):
        when = run.started_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        ids = {item.source_id for item in run.items}
        for note in run.notes or []:
            for prefix in ("dream verification receipt: ", "dream source recheck attempt: "):
                if not note.startswith(prefix):
                    continue
                try:
                    value = json.loads(note[len(prefix):])
                except (ValueError, TypeError):
                    continue
                if isinstance(value, dict) and isinstance(value.get("target_ids"), list):
                    ids.update(item for item in value["target_ids"] if isinstance(item, str))
        for entry_id in ids:
            if entry_id not in attempted or when > attempted[entry_id]:
                attempted[entry_id] = when
    return attempted


async def _detect_separated_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None,
) -> list[DreamRecheckSignal]:
    """Find recheck hypotheses without creating candidate/evidence rows.

    Dream signals are not candidate facts. Each existing entry proceeds through
    complete source reopening and support verification independently. Runtime
    maintenance can confirm, retire, or retain it without staging new facts.
    """

    store = backend.structured_store.knowledge_store
    current = await store.list_entries(project_name)
    covered = await _scope_upgrade_coverage(backend, project_name)
    attempted = await _scope_recheck_attempt_times(backend, project_name)
    source_reviews, _ = await _current_source_reviews(backend, project_name)
    held_for_review = {entry_id for entry_id, row in source_reviews.items()
        if cast(datetime, _source_review_due_at(row)) > _now()}
    signals: list[DreamRecheckSignal] = []
    seen: set[tuple[str, tuple[str, ...], str | None]] = set()

    def add(signal: DreamRecheckSignal) -> None:
        # Preserve complete groups: do not silently remove an unavailable member.
        if any(entry_id in held_for_review for entry_id in signal.target_ids):
            return
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
        # Report titles name an attributed account, never a conflicting claim.
        # Their pending scope checks are selected independently below.
        if entry.source_report is not None:
            continue
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
        if entry.id not in covered:
            add(DreamRecheckSignal(
                kind="stale", target_ids=(entry.id,), proposed_action="replace",
                risk="medium", reason="Dream upgrades this existing row to complete claim-scope verification.",
                cause_id="scope_partition_v3",
            ))
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
    # Untouched entries precede failed attempts across both entry kinds.
    # Real group/feedback signal slots stay unchanged.
    by_id = {entry.id: entry for entry in current}
    report_slots = [index for index, signal in enumerate(signals)
                    if signal.cause_id == "scope_partition_v3"]
    ordered = sorted((signals[index] for index in report_slots), key=lambda signal: (
        attempted.get(signal.target_ids[0], datetime.min.replace(tzinfo=timezone.utc)),
        by_id[signal.target_ids[0]].source_report is not None,
        by_id[signal.target_ids[0]].verified_at or datetime.min.replace(tzinfo=timezone.utc),
        signal.target_ids[0],
    ))
    for index, ordered_signal in zip(report_slots, ordered):
        signals[index] = ordered_signal
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


async def _prepare_source_backed_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path,
    entries: list[KnowledgeEntry],
) -> tuple[list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]], dict[str, tuple[str, str]]]:
    """Reopen each unique run target completely, retaining its exact snapshot."""

    store = backend.structured_store.knowledge_store
    rechecked: list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]] = []
    skipped: dict[str, tuple[str, str]] = {}
    for entry in {entry.id: entry for entry in entries}.values():
        sources = await store.list_sources(entry.id)
        validation, reopened, effective_sources = await reopen_dream_knowledge_sources(
            backend,
            project_name=project_name,
            sources=sources,
            project_root=project_root,
        )
        if validation.verification_outcome != "verified":
            missing = (validation.verification_outcome == "unverified"
                and bool(validation.reason_codes)
                and set(validation.reason_codes) <= _MISSING_SOURCE_REASONS)
            if missing and len(sources) > 1:
                # The shared reopener stops at its first unavailable source.
                # A missing first source must not mask a later role/hash/path failure.
                for source_row in sources:
                    source_validation, _source_text, _effective = await reopen_dream_knowledge_sources(
                        backend, project_name=project_name, sources=[source_row], project_root=project_root,
                    )
                    if (source_validation.verification_outcome != "verified" and not (
                            source_validation.verification_outcome == "unverified"
                            and source_validation.reason_codes
                            and set(source_validation.reason_codes) <= _MISSING_SOURCE_REASONS)):
                        missing = False
                        validation = source_validation
                        break
            skipped[entry.id] = (
                "Dream could not reopen every policy-eligible current source "
                "for this entry; current knowledge was left unchanged.",
                ("source_missing:" + ",".join(validation.reason_codes)) if missing else
                str(validation.verification_outcome or "unverified") + ":" + ",".join(validation.reason_codes),
            )
        elif any(item.truncated for item in reopened):
            skipped[entry.id] = (
                "Dream reopened only a bounded source excerpt; current knowledge "
                "was left unchanged rather than inferring a semantic result.",
                "truncated",
            )
        elif not any(item.content for item in reopened):
            skipped[entry.id] = (
                "Dream reopened no readable source text; current knowledge was left unchanged.",
                "unreadable",
            )
        elif len(reopened) != len(effective_sources) or any(not item.content for item in reopened):
            skipped[entry.id] = (
                "Dream could not bind every reopened source to readable evidence.",
                "source_binding_incomplete",
            )
        else:
            rechecked.append((entry, validation, tuple(reopened), tuple(effective_sources)))
    return rechecked, skipped


async def _verify_source_backed_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    rechecked: list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]],
    provider: Any,
    deadline: datetime | None = None,
    receipts: list[str] | None = None,
) -> dict[str, Any]:
    """Verify the complete unique target set once, sharing identical source text."""

    if not rechecked:
        return {}

    verification_manifest = {
        "contract_version": DREAM_SOURCE_RECHECK_CONTRACT,
        "scope_partition_required": True,
        "project_name": project_name,
        "candidates": [
            {
                "candidate_index": index,
                "kind": "memory",
                # This is an existing canonical entry's visible project scope,
                # not a proposed write route inferred from candidate prose.
                "current_knowledge_project": entry.project_name,
                "statement": entry.statement,
                "title": entry.title,
                "scope_text": dream_scope_text(entry),
                "scope_partition_boundaries": ([] if entry.source_report is not None else [len(entry.title) + 1]),
                "source_kind": validation.evidence_basis,
                **({"source_report": entry.source_report.model_dump(mode="json", exclude={"text"})}
                   if entry.source_report is not None else {}),
                # The shared verification owner projects only candidate.sources
                # and session_context into its deduplicated source_excerpts.
                # A caller-supplied top-level source_excerpts is overwritten.
                "sources": [
                    {
                        "kind": source.source_kind,
                        "project_name": source.project_name,
                        "content_sha256": source.content_sha256,
                        "content": item.content,
                        **({
                            "role": entry.source_report.speaker,
                            "content_scope": "native_speaker_only; attributed source report, not external current truth",
                        } if entry.source_report is not None else {
                            "role": "user",
                        } if source.source_kind == "user_statement" else {}),
                    }
                    for item, source in zip(reopened, sources)
                ],
            }
            for index, (entry, validation, reopened, sources) in enumerate(rechecked)
        ],
    }
    cancelled = threading.Event()

    def heartbeat() -> None:
        if cancelled.is_set() or (deadline is not None and _now() >= deadline):
            raise ProviderError("Dream verification deadline reached", kind="transient")

    def record_result(result: Any, *, error: BaseException | None = None) -> None:
        if receipts is None:
            return
        results = list(getattr(error, "attempt_results", ())) if error else [result]
        attempts = list(getattr(error, "native_attempts", ())) if error else list(
            getattr(result, "native_attempts", ()))
        receipts.append("dream verification receipt: " + json.dumps({
            "target_ids": [row[0].id for row in rechecked],
            "status": "failed" if error else "completed",
            "error_type": type(error).__name__ if error else None,
            "results": [{key: getattr(value, key, None) for key in (
                "input_tokens", "output_tokens", "total_tokens", "duration_seconds",
                "input_sha256", "response_sha256", "schema_valid",
            )} for value in results],
            "verification_points": [
                value.receipt().get("verification_points", []) for value in results
                if callable(getattr(value, "receipt", None))
            ],
            "native_attempts": [{key: value.get(key) for key in (
                "call_id", "status", "server_pid", "thread_id", "turn_id",
                "model_dispatched", "terminal", "thread_closed", "duration_seconds",
                "known_usage_subtotal", "unknown_response_usage_count", "usage", "error_type",
            )} for value in attempts],
            "usage_unknown": bool(
                (error and not results and not attempts)
                or any(value.get("model_dispatched") and not value.get("usage") for value in attempts)
                or any(getattr(value, "total_tokens", None) is None for value in results)
            ),
        }, sort_keys=True))

    heartbeat()
    task = asyncio.create_task(asyncio.to_thread(
        provider.verify, verification_manifest,
        runtime_dir=Path(backend.data_dir) / "autonomous" / "provider-runtime",
        heartbeat=heartbeat,
    ))
    try:
        verification_result = await asyncio.shield(task)
    except asyncio.CancelledError:
        # Cancelling to_thread does not cancel the native call. Its existing
        # heartbeat polls within 15s; native interruption and owned-process
        # cleanup are bounded separately. Reap that call before returning.
        cancelled.set()
        try:
            verification_result = await asyncio.wait_for(asyncio.shield(task), timeout=45)
        except Exception as exc:
            record_result(None, error=exc)
        else:
            record_result(verification_result)
        raise
    except Exception as exc:
        record_result(None, error=exc)
        raise
    else:
        record_result(verification_result)
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
    checked: dict[str, Any] = {}
    for index, row in enumerate(rechecked):
        point = by_index[index]
        scope = verification_scope_status(point, dream_scope_text(row[0]))
        if scope not in {"source_scope_durable", "source_scope_session_only"}:
            point = point.model_copy(update={"future_scope": "unclear"})
        elif scope == "source_scope_session_only":
            point = point.model_copy(update={"future_scope": "session_only"})
        checked[row[0].id] = point
    return checked


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
    recheck_cache: list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]] | None = None,
    source_skip_cache: dict[str, tuple[str, str]] | None = None,
    verification_cache: dict[str, Any] | None = None,
) -> list[DreamItem]:
    """Apply one original signal group using source-bound run-local verification."""

    source_kind = f"knowledge_{signal.kind}"
    if provider is None:
        return [
            DreamItem(
                source_kind=source_kind,
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
    if recheck_cache is None:
        recheck_cache, source_skip_cache = await _prepare_source_backed_rechecks(
            backend, project_name=project_name, project_root=project_root, entries=entries,
        )
    by_id = {row[0].id: row for row in recheck_cache}
    rechecked = [by_id[entry.id] for entry in entries if entry.id in by_id]
    skipped_items: list[DreamItem] = []
    for entry in entries:
        if entry.id in by_id:
            continue
        reason, status = (source_skip_cache or {}).get(entry.id, (
            "Dream target was not available during this run's complete source preparation.",
            "not_prepared",
        ))
        skipped_items.append(_skipped_recheck_item(
            entry, signal=signal, reason=reason, source_status=status,
        ))
    if not rechecked:
        return skipped_items
    verification_by_id = verification_cache
    if verification_by_id is None:
        verification_by_id = await _verify_source_backed_rechecks(
            backend, project_name=project_name, rechecked=rechecked, provider=provider,
        )
    if any(row[0].id not in verification_by_id for row in rechecked):
        raise ProviderError("Dream run cache is missing a source-bound verification", kind="unrecoverable")

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
                semantic_support=verification_by_id[entry.id].semantic_support,
                future_scope=verification_by_id[entry.id].future_scope,
                verification_reason=verification_by_id[entry.id].reason,
                scope_verification=verification_by_id[entry.id],
                source_excerpts=tuple(
                    {
                        "source_kind": item.source_kind,
                        "content": str(item.content),
                    }
                    for item in reopened
                    if item.content
                ),
            )
            for entry, _validation, reopened, effective_sources in rechecked
        ],
    )
    plan = build_dream_maintenance_plan(prepared)
    if not allow_retire:
        for point in plan:
            if point["disposition"] == "reject":
                point.update(
                    disposition="no_write",
                    matched_truth_ids=[],
                    reason="Dream policy disabled the proposed current-knowledge retirement.",
                )
    outcomes = await apply_dream_assimilation(
        backend,
        prepared=prepared,
        plan=plan,
    )
    return skipped_items + [
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
    resume_run_id: str | None = None,
) -> DreamRun:
    """Run one bounded slice; automatic callers resume the same complete ledger."""

    store = cast(LocalStructuredStore, backend.structured_store)
    previous = ([await store.get_dream_run(resume_run_id)] if resume_run_id else
        await store.list_dream_runs(project_name, limit=1))
    if resume_run_id and (not previous[0] or previous[0].project_name != project_name
            or previous[0].status != "continuing"):
        raise ValueError("requested Dream continuation is not resumable for this project")
    resumed = previous[0] if (reflection_job_id and previous and previous[0]
        and previous[0].status == "continuing"
        and previous[0].continuation.get("version") == "dream-slices-v3") else None
    run_id = resumed.id if resumed is not None else str(uuid4())
    selected_provider = semantic_provider or _dream_provider_from_config(config, host_client=host_client)
    completed_run: DreamRun | None = None
    try:
        completed_run = await _dream_once(
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            source=source,
            reflection_job_id=reflection_job_id,
            deadline=deadline,
            semantic_provider=selected_provider,
            host_client=host_client,
            _run_id=run_id,
            _resume=resumed,
        )
        return completed_run
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
            run.notes.append("dream failure locations: " + json.dumps(exception_locations(exc)))
            await store.save_dream_run(run)
        raise
    finally:
        if semantic_provider is None and selected_provider is not None:
            close = getattr(selected_provider, "close", None)
            if callable(close):
                # Verification has already reaped its bounded heartbeat call.
                store = cast(LocalStructuredStore, backend.structured_store)
                try:
                    closed = await asyncio.wait_for(asyncio.to_thread(close), timeout=20)
                except Exception as exc:
                    run = completed_run or await store.get_dream_run(run_id)
                    if run is not None:
                        run.status = "failed"
                        run.completed_at = _now()
                        run.notes = list(run.notes or [])
                        run.notes.append(f"dream provider close failed: {type(exc).__name__}")
                        await store.save_dream_run(run)
                    raise
                run = completed_run or await store.get_dream_run(run_id)
                if run is not None:
                    run.notes = list(run.notes or [])
                    run.notes.append("dream provider close: " + json.dumps(closed, sort_keys=True))
                    await store.save_dream_run(run)


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
    _resume: DreamRun | None = None,
) -> DreamRun:
    """Run one Dream maintenance pass and persist its bounded job status."""
    store = cast(LocalStructuredStore, backend.structured_store)
    started_at = _resume.started_at if _resume is not None else _now()
    notes: list[str] = list(_resume.notes or []) if _resume is not None else []
    items: list[DreamItem] = list(_resume.items) if _resume is not None else []
    source_reviews, _review_fingerprints = await _current_source_reviews(backend, project_name)

    run_stub = DreamRun(
        id=_run_id or str(uuid4()),
        project_name=project_name,
        started_at=started_at,
        completed_at=None,
        status="processing",
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        # Preserve prior slice receipts even if this process exits before its
        # first progress checkpoint. A processing stub must not erase them.
        items=list(items),
        notes=notes if notes else None,
        continuation=dict(_resume.continuation) if _resume is not None else {},
        source_reviews=dict(source_reviews),
    )
    await store.save_dream_run(run_stub)

    if _resume is not None:
        recheck_signals = [DreamRecheckSignal(
            kind=row["kind"], target_ids=tuple(row["target_ids"]),
            proposed_action=row["proposed_action"], risk=row["risk"],
            reason=row["reason"], cause_id=row.get("cause_id"),
        ) for row in run_stub.continuation["signals"]]
    else:
        recheck_signals = await _detect_separated_rechecks(
            backend, project_name=project_name, project_root=project_root,
        )
    selected_provider = semantic_provider or _dream_provider_from_config(
        config,
        host_client=host_client,
    )

    async def persist_progress(*, check_deadline: bool = True) -> None:
        checkpoint["completed_signal_indexes"] = sorted(completed_signal_indexes)
        checkpoint["unresolved_scope"] = dict(unresolved_scope)
        checkpoint["verification"] = dict(saved_verification)
        run_stub.continuation = dict(checkpoint)
        run_stub.source_reviews = dict(source_reviews)
        run_stub.items = list(items)
        run_stub.notes = list(notes)
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

    recheck_cache: list[tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...]]] | None = None
    source_skip_cache: dict[str, tuple[str, str]] | None = None
    verification_cache: dict[str, Any] = {}
    verification_batches: dict[int, list[str]] = {}
    entry_snapshots: dict[str, KnowledgeEntry] = {}
    all_target_ids = list(dict.fromkeys(
        target_id for signal in recheck_signals for target_id in signal.target_ids
    ))
    checkpoint = dict(run_stub.continuation)
    checkpoint.setdefault("version", "dream-slices-v3")
    checkpoint.setdefault("signals", [dict(
        kind=signal.kind, target_ids=list(signal.target_ids),
        proposed_action=signal.proposed_action, risk=signal.risk,
        reason=signal.reason, cause_id=signal.cause_id,
    ) for signal in recheck_signals])
    checkpoint.setdefault("target_ids", all_target_ids)
    checkpoint.setdefault("max_slices", len(all_target_ids) + 1)
    checkpoint["slice_count"] = int(checkpoint.get("slice_count", 0)) + 1
    completed_signal_indexes: set[int] = set(checkpoint.get("completed_signal_indexes", []))
    unresolved_scope: dict[str, str] = dict(checkpoint.get("unresolved_scope", {}))
    if _resume is not None and checkpoint.get("verification_contract") != DREAM_SOURCE_RECHECK_CONTRACT:
        applied_targets = {item.source_id for item in items if item.final_action == "applied"}
        # A new source-support contract may resolve an earlier no-write result.
        # Keep its actual failed attempt in the ledger, but never reapply an
        # already changed group or replace the original complete manifest.
        completed_signal_indexes = {index for index in completed_signal_indexes
            if not (set(recheck_signals[index].target_ids).intersection(unresolved_scope)
                    and not set(recheck_signals[index].target_ids).intersection(applied_targets))}
    checkpoint["verification_contract"] = DREAM_SOURCE_RECHECK_CONTRACT
    saved_verification: dict[str, Any] = dict(checkpoint.get("verification", {}))
    new_verification_batches = 0
    verification_deadline = deadline
    if deadline is not None:
        available = max(0.0, (deadline - _now()).total_seconds())
        verification_deadline = deadline - timedelta(seconds=min(15, available * 0.15))

    def source_binding(row: Any) -> str:
        entry, validation, reopened, sources = row
        payload = {
            "verification_contract": DREAM_SOURCE_RECHECK_CONTRACT,
            "current_knowledge_project": entry.project_name,
            "semantic_fingerprint": _scope_fingerprint(entry),
            "evidence_basis": validation.evidence_basis,
            "sources": [{"kind": source.source_kind, "locator": source.locator,
                "content_sha256": source.content_sha256} for source in sources],
            "reopened": [hashlib.sha256(item.content.encode()).hexdigest() for item in reopened],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
            default=str, separators=(",", ":")).encode()).hexdigest()

    def point_proof(point: Any, text: str) -> dict[str, Any] | None:
        # A checkpoint is metadata only. Invalid/incomplete partitions cannot
        # be reused and must go through full source reopening and verification.
        if not point.scope_segments or "".join(part.text for part in point.scope_segments) != text:
            return None
        segments = []
        offset = 0
        for part in point.scope_segments:
            end = offset + len(part.text)
            segments.append({
                "char_start": offset, "char_end": end,
                "text_sha256": hashlib.sha256(part.text.encode()).hexdigest(),
                "content_role": part.content_role, "source_use": part.source_use,
                "future_scope": part.future_scope, "standalone": part.standalone,
                "source_support": part.source_support,
            })
            offset = end
        return {
            "proof_version": "scope-offsets-v2",
            "candidate_index": point.candidate_index,
            "semantic_support": point.semantic_support, "future_scope": point.future_scope,
            "source_use": point.source_use,
            "reason_sha256": hashlib.sha256(point.reason.encode()).hexdigest(),
            "scope_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "scope_segments": segments,
            "claim_units": [{
                **unit.model_dump(mode="json"),
                "text_sha256": hashlib.sha256("".join(
                    part.text for part in point.scope_segments[unit.first_segment:unit.end_segment_exclusive]
                ).encode()).hexdigest(),
            } for unit in point.claim_units],
        }

    def restore_point(proof: Any, text: str) -> CandidateVerificationPoint | None:
        try:
            if (not isinstance(proof, dict) or proof.get("proof_version") != "scope-offsets-v2"
                    or proof.get("scope_text_sha256") != hashlib.sha256(text.encode()).hexdigest()):
                return None
            segments = []
            offset = 0
            for part in proof["scope_segments"]:
                start, end = part["char_start"], part["char_end"]
                if (type(start) is not int or type(end) is not int
                        or start != offset or not start < end <= len(text)
                        or "text" in part):
                    return None
                current_text = text[start:end]
                if hashlib.sha256(current_text.encode()).hexdigest() != part["text_sha256"]:
                    return None
                segments.append({"text": current_text, **{key: part[key] for key in (
                    "content_role", "source_use", "future_scope", "standalone", "source_support",
                )}})
                offset = end
            if offset != len(text) or not segments:
                return None
            units = []
            for unit in proof["claim_units"]:
                first, end = unit["first_segment"], unit["end_segment_exclusive"]
                if (type(first) is not int or type(end) is not int
                        or not 0 <= first < end <= len(segments)
                        or hashlib.sha256("".join(part["text"] for part in segments[first:end]).encode()).hexdigest()
                        != unit["text_sha256"]):
                    return None
                units.append({key: unit[key] for key in (
                    "first_segment", "end_segment_exclusive", "standalone",
                    "source_support", "source_use", "future_scope",
                )})
            return CandidateVerificationPoint.model_validate({
                **{key: proof[key] for key in (
                    "candidate_index", "semantic_support", "future_scope", "source_use",
                )},
                "reason": "Reused this run's source-bound verification after current content and partition hash checks.",
                "scope_segments": segments,
                "claim_units": units,
            })
        except (KeyError, TypeError, ValueError):
            return None

    async def review_missing_source(entry: KnowledgeEntry, item: DreamItem) -> bool:
        current_entries = await backend.structured_store.knowledge_store.list_entries(project_name)
        current_by_id = {row.id: row for row in current_entries}
        current = current_by_id.get(entry.id)
        fingerprint = _scope_fingerprint(entry)
        if current is None or _scope_fingerprint(current) != fingerprint:
            return False
        duplicates = [row for row in current_entries if row.id != entry.id
            and _scope_fingerprint(row) == fingerprint]
        comparisons = [row for row in current_entries if row.id != entry.id
            and entry.source_report is None and row.source_report is None
            and row.module_path == entry.module_path and row.title == entry.title
            and row.statement != entry.statement]
        feedback = await backend.structured_store.query_retrieval_signals(
            project_name, signal_type="context_outcome", target_kind="knowledge_entry", limit=200,
        )
        latest_feedback = next((row for row in feedback if row.target_id == entry.id), None)
        negative = latest_feedback is not None and latest_feedback.value is not None and latest_feedback.value <= 0
        recommendation = ("consider_exact_duplicate" if duplicates else
            "compare_current_claims" if comparisons else
            "review_deletion_candidate" if negative else "keep_pending_user_judgment")
        explanation = ("Current entries have identical complete claim and attribution fingerprints; review the retained copy before deletion."
            if duplicates else "Current ordinary entries share a title and module but differ in text; compare them without assuming a contradiction or replacement."
            if comparisons else "Negative retrieval feedback warrants review; it does not establish falsehood or authorize deletion."
            if negative else "The original source is unavailable; retain this recallable memory until the user judges its current usefulness.")
        reviewed_at = _now()
        row = {
            "policy_version": "missing-source-review-v1", "fingerprint": fingerprint,
            "last_reviewed_at": reviewed_at.isoformat(),
            "next_review_at": (reviewed_at + timedelta(days=SOURCE_REVIEW_INTERVAL_DAYS)).isoformat(),
            "interval_days": SOURCE_REVIEW_INTERVAL_DAYS,
            "source_status": "unavailable", "verification_status": "not_reverified",
            "disposition": "kept_unverified", "needs_human_review": True,
            "recommendation": recommendation, "review_reason": explanation,
            "reason_codes": str(item.result["source_status"]).split(":", 1)[1].split(","),
            "related_current_entries": [{"entry_id": other.id, "fingerprint": _scope_fingerprint(other)}
                for other in [*duplicates, *comparisons]],
            "negative_feedback_id": latest_feedback.id if negative and latest_feedback is not None else None,
            "automatic_deletion_authorized": False,
        }
        source_reviews[entry.id] = row
        item.result.update(source_review=dict(row), truth_change="none")
        item.reason = explanation
        return True

    async def continue_later() -> DreamRun:
        update_remaining()
        await persist_progress(check_deadline=False)
        run_stub.status = "continuing"
        run_stub.completed_at = None
        run_stub.duration_ms = int((_now() - started_at).total_seconds() * 1000)
        await store.save_dream_run(run_stub)
        return run_stub
    if _resume is None:
        notes.append("dream target manifest: " + json.dumps({
        "target_ids": all_target_ids,
        "groups": [{"kind": signal.kind, "target_ids": list(signal.target_ids)}
                   for signal in recheck_signals],
        }, sort_keys=True))

    def update_remaining() -> None:
        prefix = "dream remaining targets: "
        notes[:] = [note for note in notes if not note.startswith(prefix)]
        notes.append(prefix + json.dumps(list(dict.fromkeys([
            *unresolved_scope,
            *(
                target_id for index, signal in enumerate(recheck_signals)
                if index not in completed_signal_indexes for target_id in signal.target_ids
            ),
        ]))))
        unresolved_prefix = "dream unresolved scope: "
        notes[:] = [note for note in notes if not note.startswith(unresolved_prefix)]
        notes.append(unresolved_prefix + json.dumps(unresolved_scope, sort_keys=True))

    update_remaining()
    if checkpoint["slice_count"] > checkpoint["max_slices"]:
        notes.append("dream continuation exhausted its finite target-derived slice limit")
        await persist_progress(check_deadline=False)
        run_stub.status = "failed"
        run_stub.completed_at = _now()
        await store.save_dream_run(run_stub)
        return run_stub
    scope_coverage = await _scope_upgrade_coverage(backend, project_name)

    def record_scope_coverage() -> None:
        prefix = "dream scope_partition_v3: "
        notes[:] = [note for note in notes if not note.startswith(prefix)]
        notes.append(prefix + json.dumps(scope_coverage, sort_keys=True))

    record_scope_coverage()
    if recheck_signals and project_root is not None and selected_provider is not None:
        # Seal all target metadata now; reopen complete evidence only as its
        # bounded batch is reached. No later target disappears from the ledger.
        target_ids = dict.fromkeys(
            target_id for signal in recheck_signals for target_id in signal.target_ids
        )
        for target_id in target_ids:
            entry = await backend.structured_store.knowledge_store.get_entry(
                target_id, project_name=project_name, project_root=project_root,
            )
            if entry is not None:
                entry_snapshots[entry.id] = entry
        notes.append("dream target snapshots: " + json.dumps([
            {"entry_id": entry.id, "fingerprint": _scope_fingerprint(entry)}
            for entry in entry_snapshots.values()
        ], sort_keys=True))
        recheck_cache, source_skip_cache = [], {}
        await persist_progress()
        batch_start = 0
        batch_ids: list[str] = []
        for index, signal in enumerate(recheck_signals):
            combined = list(dict.fromkeys([*batch_ids, *signal.target_ids]))
            if batch_ids and len(combined) > 4:
                verification_batches[batch_start] = batch_ids
                batch_start, batch_ids = index, list(signal.target_ids)
            else:
                batch_ids = combined
        if batch_ids:
            verification_batches[batch_start] = batch_ids
        for start, ids in list(verification_batches.items()):
            end = next((index for index in sorted(verification_batches) if index > start), len(recheck_signals))
            unfinished = next((index for index in range(start, end)
                if index not in completed_signal_indexes), None)
            if unfinished is not None and unfinished != start:
                verification_batches[unfinished] = verification_batches.pop(start)

    for signal_index, signal in enumerate(recheck_signals):
        if signal_index in completed_signal_indexes:
            continue
        await persist_progress()
        if signal_index in verification_batches:
            # Verification is per entry. Large genuine groups retain their
            # shared maintenance decision only after all chunks are verified.
            batch_ids = verification_batches[signal_index]
            for offset in range(0, len(batch_ids), 4):
                target_chunk = batch_ids[offset:offset + 4]
                prepared_by_id = {row[0].id: row for row in recheck_cache or []}
                fresh = [entry_snapshots[target_id] for target_id in target_chunk
                         if target_id in entry_snapshots and target_id not in prepared_by_id
                         and target_id not in (source_skip_cache or {})]
                if fresh:
                    notes.append("dream source recheck attempt: " + json.dumps({
                        "target_ids": [entry.id for entry in fresh], "stage": "source_prepare_started",
                    }, sort_keys=True))
                    await persist_progress()
                reopened, skipped = await _prepare_source_backed_rechecks(
                    backend, project_name=project_name, project_root=cast(str | Path, project_root),
                    entries=fresh,
                )
                cast(list[Any], recheck_cache).extend(reopened)
                cast(dict[str, tuple[str, str]], source_skip_cache).update(skipped)
                prepared_by_id.update({row[0].id: row for row in reopened})
                await persist_progress()
                for target_id in target_chunk:
                    row = prepared_by_id.get(target_id)
                    prior = saved_verification.get(target_id)
                    if row is not None and prior is not None:
                        restored = (restore_point(prior.get("point"), dream_scope_text(row[0]))
                            if prior.get("binding") == source_binding(row) else None)
                        if restored is not None:
                            verification_cache[target_id] = restored
                        else:
                            saved_verification.pop(target_id, None)
                batch_rows = [prepared_by_id[target_id] for target_id in target_chunk
                              if target_id in prepared_by_id and target_id not in verification_cache]
                # Only the bounded natural worker owns the continuation loop.
                # Direct CLI/MCP runs without a deadline retain a complete pass.
                if batch_rows and new_verification_batches and deadline is not None:
                    return await continue_later()
                try:
                    if batch_rows:
                        new_verification_batches += 1
                    verification_cache.update(await _verify_source_backed_rechecks(
                        backend, project_name=project_name,
                        rechecked=batch_rows, provider=selected_provider,
                        deadline=verification_deadline, receipts=notes,
                    ))
                finally:
                    notes.append("dream verified targets: " + json.dumps(list(verification_cache)))
                    for row in batch_rows:
                        entry = row[0]
                        entry_id = entry.id
                        point = verification_cache.get(entry_id)
                        if point is None:
                            continue
                        proof = point_proof(point, dream_scope_text(entry))
                        if proof is not None:
                            saved_verification[entry_id] = {
                            "binding": source_binding(row),
                            "semantic_fingerprint": _scope_fingerprint(entry),
                            "source_proofs": [{
                                "kind": source.source_kind,
                                "locator_sha256": hashlib.sha256(source.locator.encode()).hexdigest(),
                                "content_sha256": source.content_sha256,
                                "source_revision": parse_qs(
                                    urlparse(source.locator).fragment or urlparse(source.locator).query
                                ).get("source_revision", [None])[0],
                            } for source in row[3]],
                            "point": proof,
                            }
                        else:
                            saved_verification.pop(entry_id, None)
                        status = verification_scope_status(point, dream_scope_text(entry))
                        if (status not in {"source_scope_durable", "source_scope_session_only"}
                                or point.semantic_support != "supported"):
                            unresolved_scope[entry_id] = status + ":" + point.semantic_support
                    record_scope_coverage()
                    update_remaining()
                    await persist_progress(check_deadline=False)
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
            if not signal_entries:
                completed_signal_indexes.add(signal_index)
                update_remaining()
                continue
            if signal.kind in {"duplicate", "conflict"}:
                for entry in signal_entries:
                    unresolved_scope[entry.id] = "group_members_changed"
                    items.append(_skipped_recheck_item(
                        entry, signal=signal,
                        reason="The original complete Dream group changed; no partial group was applied.",
                        source_status="group_members_changed",
                    ))
                completed_signal_indexes.add(signal_index)
                update_remaining()
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
            completed_signal_indexes.add(signal_index)
            update_remaining()
            continue
        group_items = await _run_source_backed_recheck_group(
                backend,
                project_name=project_name,
                project_root=str(project_root),
                entries=signal_entries,
                signal=signal,
                run_id=run_stub.id,
                provider=selected_provider,
                allow_retire=True,
                recheck_cache=recheck_cache,
                source_skip_cache=source_skip_cache,
                verification_cache=verification_cache,
        )
        items.extend(group_items)
        completed_signal_indexes.add(signal_index)
        for item in group_items:
            if item.final_action == "rejected":
                point = verification_cache.get(item.source_id)
                if (point is not None and point.semantic_support == "supported"
                        and point.future_scope == "session_only"):
                    original = entry_snapshots.get(item.source_id)
                    allowed = original is not None and dream_temporary_retirement_allowed(original, point)
                    unresolved_scope[item.source_id] = (
                        "temporary_retirement_rejected" if allowed else
                        "source_scope_session_only:retirement_not_authorized"
                    )
            if item.final_action == "skipped":
                status = str(item.result.get("source_status", "source_unavailable"))
                original = entry_snapshots.get(item.source_id)
                if (status.startswith("source_missing:") and original is not None
                        and await review_missing_source(original, item)):
                    unresolved_scope.pop(item.source_id, None)
                else:
                    unresolved_scope[item.source_id] = status
            if item.final_action == "applied":
                source_reviews.pop(item.source_id, None)
            if item.final_action == "applied" and item.result.get("truth_change") in {"refine", "deleted"}:
                unresolved_scope.pop(item.source_id, None)
            if item.final_action == "applied" and item.result.get("truth_change") == "verification_refreshed":
                entry = entry_snapshots[item.source_id]
                point = verification_cache[item.source_id]
                if (verification_scope_status(point, dream_scope_text(entry)) == "source_scope_durable"
                        and point.semantic_support == "supported"):
                    scope_coverage[entry.id] = {
                        "fingerprint": _scope_fingerprint(entry), "scope_status": "source_scope_durable",
                        "semantic_support": "supported",
                    }
                    unresolved_scope.pop(entry.id, None)
            if item.final_action != "applied" or item.result.get("truth_change") != "refine":
                continue
            for truth_id in item.result.get("truth_ids") or []:
                retained = await backend.structured_store.knowledge_store.get_entry(
                    truth_id, project_name=project_name, project_root=project_root,
                )
                if retained is not None:
                    scope_coverage[retained.id] = {
                        "fingerprint": _scope_fingerprint(retained),
                        "scope_status": "source_scope_durable", "semantic_support": "supported",
                    }
        record_scope_coverage()
        update_remaining()
        await persist_progress()

    completed_at = _now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    final_status: Literal["completed", "failed"] = (
        "failed"
        if unresolved_scope or any(item.final_action == "failed" for item in items)
        else "completed"
    )
    run = DreamRun(
        id=run_stub.id,
        project_name=project_name,
        started_at=started_at,
        completed_at=completed_at,
        status=final_status,
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        items=items,
        duration_ms=duration_ms,
        notes=notes if notes else None,
        continuation={**checkpoint, "completed_signal_indexes": sorted(completed_signal_indexes),
            # Retain finite metadata proofs for deletion/refinement audit after
            # source locator rows are normally removed; never retain bodies.
            "unresolved_scope": dict(unresolved_scope), "verification": dict(saved_verification)},
        source_reviews=dict(source_reviews),
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

    current_reviews, _current_fingerprints = await _current_source_reviews(backend, project_name)
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
        "source_reviews": dict(current_reviews),
        "source_review_interval_days": SOURCE_REVIEW_INTERVAL_DAYS,
        "needs_human_review": any(row.get("needs_human_review") for row in current_reviews.values()),
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
    if last_run is not None and last_run.status == "continuing":
        return DreamSchedulerDecision(True, "dream continuation pending", last_run_id=last_run.id)
    source_reviews, current_fingerprints = await _current_source_reviews(backend, project_name)
    now = _now()
    due_reviews = [entry_id for entry_id, row in source_reviews.items()
        if cast(datetime, _source_review_due_at(row)) <= now]
    changed_reviews = [entry_id for entry_id in (last_run.source_reviews if last_run else {})
        if entry_id in current_fingerprints and entry_id not in source_reviews]
    if due_reviews or changed_reviews:
        return DreamSchedulerDecision(True, "retained memory source review is due",
            last_run_id=last_run.id if last_run else None)
    review_dates = [cast(datetime, _source_review_due_at(row)) for row in source_reviews.values()]
    next_source_review = min(review_dates) if review_dates else None
    latest_activity = await _latest_project_activity(backend, project_name)
    if latest_activity is None:
        return DreamSchedulerDecision(False, "no project activity to dream over",
            next_eligible_at=next_source_review)
    if last_run is not None and latest_activity <= last_run.started_at:
        return DreamSchedulerDecision(
            False,
            "no new project activity since the last dream run",
            last_run_id=last_run.id, next_eligible_at=next_source_review,
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
    resume_run_id: str | None = None,
) -> dict[str, Any]:
    """Run one Dream tick and record its independent diagnostic lifecycle."""

    diagnostic = DiagnosticRun(
        backend.data_dir,
        operation="dream",
        project_name=project_name,
        project_root=project_root,
parent_run_id=diagnostic_parent_id(),
        references={
            "trigger_id": trigger_id,
            "job_id": trigger_job_id,
            "source": source,
            "client": host_client,
        },
    )
    diagnostic.emit("accepted", "running")
    diagnostic.emit("started", "running")
    try:
        with diagnostic.activate_children():
            result = await _dream_auto_tick_core(
                backend,
                project_name=project_name,
                project_root=project_root,
                config=config,
                source=source,
                trigger_id=trigger_id,
                trigger_job_id=trigger_job_id,
                host_client=host_client,
                resume_run_id=resume_run_id,
            )
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary.
        diagnostic.emit(
            "failed",
            "failed",
            error={
                "kind": "dream_exception",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
            details=exception_locations(exc),
        )
        raise
    status = str(result.get("status") or "failed")
    references = {
        key: result.get(key)
        for key in ("job_id", "run_id", "trigger_id")
        if result.get(key) is not None
    }
    if status == "completed":
        diagnostic.emit("completed", "completed", references=references)
    elif status == "skipped":
        diagnostic.emit("skipped", "skipped", references=references)
    elif status == "continuing":
        diagnostic.emit("deferred", "deferred", references=references,
            details={"continuation": result.get("continuation")})
    elif status in {"deferred", "blocked"}:
        diagnostic.emit(
            status,
            status,
            references=references,
            error=result.get("error") or result.get("reason"),
        )
    else:
        diagnostic.emit(
            "failed",
            "failed",
            references=references,
            error=result.get("error") or {"kind": "dream_failed", "message": status},
            details=result.get("failure_details"),
        )
    return result


async def _dream_auto_tick_core(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    config: MergedConfig,
    source: DreamSource = "agent",
    trigger_id: str | None = None,
    trigger_job_id: str | None = None,
    host_client: str | None = None,
    resume_run_id: str | None = None,
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
    if resume_run_id:
        requested_run = await cast(LocalStructuredStore, backend.structured_store).get_dream_run(resume_run_id)
        if (requested_run is None or requested_run.project_name != project_name
                or requested_run.status != "continuing"
                or requested_run.continuation.get("version") != "dream-slices-v3"):
            return {"success": False, "status": "failed", "project_name": project_name,
                "run_id": resume_run_id, "reason": "requested Dream continuation is not resumable"}
        # A continuation is the same maintenance request, never another source job.
        trigger_job_id = None
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
    force_for_hook_session = hook_session is not None or resume_run_id is not None
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
        run = await _run_dream_with_progress_timeout(
            backend,
            project_name=project_name,
            project_root=project_root,
            config=config,
            source=source,
            reflection_job_id=job.id,
            timeout_seconds=config.dream_auto_max_runtime_seconds,
            host_client=host_client,
                resume_run_id=resume_run_id,
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
        job.phase = "metabolism" if run.status == "continuing" else "done"
        job.status = ("retryable" if run.status == "continuing" else
            "completed" if run.status == "completed" else "failed")
        job.output_candidate_ids = [item.source_id for item in run.items]
        job.completed_at = run.completed_at
        job.updated_at = _now()
        if run.status == "failed":
            job.error = "dream: one or more dream items failed"
        backend.reflection_job_store.save(job)
        return await _record_dream_tick(
            backend,
            project_name=project_name,
            source=source,
            trigger_id=trigger_id,
            payload={
                "success": run.status in {"completed", "continuing"},
                "status": run.status,
                "continuation": ({
                    "run_id": run.id, "project_name": project_name,
                    "project_root": project_root,
                    "targets_remaining": list(dict.fromkeys([
                        *run.continuation.get("unresolved_scope", {}),
                        *(target_id for index, signal in enumerate(run.continuation.get("signals", []))
                          if index not in run.continuation.get("completed_signal_indexes", [])
                          for target_id in signal["target_ids"]),
                    ])),
                    "unresolved_scope": dict(run.continuation.get("unresolved_scope", {})),
                    "slice_count": run.continuation.get("slice_count", 0),
                    "max_slices": run.continuation.get("max_slices", 0),
                } if run.status == "continuing" else None),
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
                "failure_details": exception_locations(exc),
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
    resume_run_id: str | None = None,
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
                resume_run_id=resume_run_id,
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
