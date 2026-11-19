"""v3.1 Auto Dream Memory Maintenance business command."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast
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
    _entry_version_snapshot,
)
from harness_mem.autonomous.models import (
    AssimilationDecision,
    CanonicalKnowledgeItem,
    CandidateVerificationDecision,
    CandidateVerificationPoint,
    OutputVerification,
    DREAM_SOURCE_RECHECK_CONTRACT,
    verification_scope_status,
)
from harness_mem.autonomous.authorization import background_on, background_status, background_reason_message
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    final_scope_payload,
    final_scope_verification_rows,
    judged_update_payload,
    bind_final_scope_judgment,
    prove_supplied_final_scope,
    validate_separated_assimilation_decision,
)
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
from harness_mem.core.schemas.source_report import report_output_scope_text


DreamSource = Literal["user", "agent", "ide_hook", "scheduler"]
DreamRecheckRow = tuple[KnowledgeEntry, Any, tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]


class _DreamSliceYield(Exception):
    """A persisted scheduling boundary, not a failed verification."""


def _verification_runtime_seconds(provider: Any | None) -> int:
    # The native executor already bounds one complete decision (including its
    # protocol and retries). Scheduling slices must not truncate that decision.
    return max(30, min(int(getattr(provider, "timeout_seconds", 300)), 900))


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


def _unresolved_fingerprint(
    entry: KnowledgeEntry,
    sources: Sequence[Any],
    *,
    feedback: Any,
    contract: str,
    reopen: str,
) -> str:
    """Content-free identity for one unresolved recheck.

    A later Stop repeats semantic work only when this value changes, the
    contract changes, feedback changes, or the stored review is due.
    """

    body = {
        "content": _scope_fingerprint(entry),
        "sources": sorted(
            (
                {
                    "kind": source.source_kind,
                    "content_sha256": source.content_sha256,
                    "locator_sha256": hashlib.sha256(source.locator.encode()).hexdigest(),
                }
                for source in sources
            ),
            key=lambda item: (item["kind"], item["locator_sha256"], item["content_sha256"]),
        ),
        "feedback_id": None if feedback is None else getattr(feedback, "id", None),
        "feedback_value": None if feedback is None else getattr(feedback, "value", None),
        "contract": contract,
        "reopen": reopen,
    }
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, default=str, separators=(",", ":"),
    ).encode()).hexdigest()


def _review_is_due(row: Mapping[str, Any] | None, now: datetime) -> bool:
    if not row:
        return True
    raw = row.get("review_after")
    if not isinstance(raw, str) or not raw:
        return True
    try:
        due = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due <= now


SOURCE_REVIEW_INTERVAL_DAYS = 30
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


async def _scope_upgrade_coverage(
    backend: LocalMemoryBackend, project_name: str, *, include_rejections: bool = False,
) -> dict[str, Any]:
    """Reuse existing run receipts for scheduling only, never source admission."""
    prefix = "dream scope_partition_v3: "
    entries = await backend.structured_store.knowledge_store.list_entries(project_name)
    current = {entry.id: _scope_fingerprint(entry) for entry in entries}
    coverage: dict[str, Any] = {}
    consumed: set[str] = set()
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
                        and entry_id not in consumed
                        and row.get("fingerprint") == current[entry_id]):
                    # A newer negative receipt supersedes an older positive
                    # receipt for the exact same current content.
                    consumed.add(entry_id)
                    coverage[entry_id] = row
    return {entry_id: row for entry_id, row in coverage.items()
            if include_rejections or (row.get("scope_status") == "source_scope_durable"
                                      and row.get("semantic_support") == "supported")}


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

    # A paraphrase can duplicate an earlier extraction without sharing its
    # spelling or title. Matching exact original-user anchors only nominates a
    # comparison; the existing semantic/final owners decide what overlaps and
    # retain every independent claim. Revisions may differ while the original
    # authored exchange remains byte-bound to the same anchor.
    anchored_groups: dict[tuple[str, str, str], dict[str, KnowledgeEntry]] = {}
    all_source_bindings: dict[str, list[str]] = {}
    for entry in current:
        if entry.source_report is not None:
            continue
        entry_sources = await store.list_sources(entry.id)
        all_source_bindings[entry.id] = sorted(json.dumps({
            "kind": source.source_kind, "locator": source.locator,
            "digest": source.content_sha256, "project": source.project_name,
            "knowledge_id": source.knowledge_id,
        }, sort_keys=True) for source in entry_sources)
        for source in entry_sources:
            if (source.source_kind != "user_statement" or source.project_name != project_name
                    or source.knowledge_id != entry.id):
                continue
            parsed = urlparse(source.locator)
            values = parse_qs(parsed.fragment or parsed.query)
            source_id = (values.get("source_id") or [""])[0]
            exchange = (values.get("exchange") or [""])[0]
            anchor = (values.get("anchor_sha256") or [""])[0]
            if (source_id and exchange.isdecimal() and int(exchange) > 0 and len(anchor) == 64
                    and all(char in "0123456789abcdef" for char in anchor)):
                key = (source_id, exchange, anchor)
                anchored_groups.setdefault(key, {})[entry.id] = entry
    for key, group in anchored_groups.items():
        if len(group) > 1:
            if len({" ".join(entry.statement.casefold().split()) for entry in group.values()}) == 1:
                continue  # The existing exact-duplicate hypothesis already owns it.
            comparison = "source-anchor:" + hashlib.sha256(json.dumps({
                "anchor": key, "members": {identity: _scope_fingerprint(entry)
                    for identity, entry in sorted(group.items())},
                "sources": {identity: all_source_bindings[identity] for identity in group},
            }, sort_keys=True).encode()).hexdigest()
            if any(comparison in (covered.get(identity, {}).get("compared_groups") or []) for identity in group):
                continue
            add(DreamRecheckSignal(kind="duplicate", target_ids=tuple(sorted(group)),
                proposed_action="merge", risk="medium",
                reason="Compare current claims from the same exact original-user anchor; consolidate overlaps while preserving independent meanings.",
                cause_id=comparison))

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
) -> tuple[list[DreamRecheckRow], dict[str, tuple[str, str]]]:
    """Reopen each unique run target completely, retaining its exact snapshot."""

    store = backend.structured_store.knowledge_store
    rechecked: list[DreamRecheckRow] = []
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
            rechecked.append((entry, validation, tuple(reopened), tuple(effective_sources), tuple(sources)))
    return rechecked, skipped


async def _run_dream_provider_call(
    backend: LocalMemoryBackend, *, provider: Any, phase: str,
    manifest: Mapping[str, Any], rechecked: Sequence[Any],
    deadline: datetime | None = None, receipts: list[str] | None = None,
) -> Any:
    """Run one existing provider phase with owned cancellation and usage receipts."""
    cancelled = threading.Event()

    def heartbeat() -> None:
        if cancelled.is_set() or (deadline is not None and _now() >= deadline):
            raise ProviderError("Dream verification deadline reached", kind="transient")
        owner_heartbeat = getattr(provider, "_dream_owner_heartbeat", None)
        if callable(owner_heartbeat):
            owner_heartbeat()

    def record_result(result: Any, *, error: BaseException | None = None) -> None:
        if receipts is None:
            return
        results = list(getattr(error, "attempt_results", ())) if error else [result]
        attempts = list(getattr(error, "native_attempts", ())) if error else list(
            getattr(result, "native_attempts", ()))
        from harness_mem.autonomous.executors.task_budget import TASK_BUDGET_REFUSAL_CODES
        refused = getattr(error, "failure_reason", None) in TASK_BUDGET_REFUSAL_CODES
        receipts.append("dream verification receipt: " + json.dumps({
            "contract_version": DREAM_SOURCE_RECHECK_CONTRACT,
            "phase": phase,
            "manifest_contract": manifest.get("contract_version"),
            "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "final_output_bindings": [{
                "candidate_index": row["candidate_index"],
                "owner_candidate_id": row.get("owner_candidate_id"),
                "title_sha256": hashlib.sha256(str(row["title"]).encode()).hexdigest(),
                "statement_sha256": hashlib.sha256(str(row["statement"]).encode()).hexdigest(),
                "scope_text_sha256": hashlib.sha256(str(row["scope_text"]).encode()).hexdigest(),
                "predecessors": [{"id": target["id"], "version": target["version"]}
                    for target in (row.get("update_context") or {}).get("predecessors", [])],
                **({"report_preservation_inventory_sha256": hashlib.sha256(json.dumps(
                    row["update_context"]["report_preservation_inventory"], ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
                    if isinstance((row.get("update_context") or {}).get(
                        "report_preservation_inventory"), dict) else {}),
            } for row in manifest.get("candidates", [])
                if manifest.get("contract_version") == "final-knowledge-scope-v1"],
            "input_fingerprint": hashlib.sha256("\n".join(
                row[0].statement for row in rechecked
            ).encode()).hexdigest(),
            "target_fingerprints": [{
                "entry_id": row[0].id,
                "content_sha256": _scope_fingerprint(row[0]),
                "sources": [{
                    "kind": source.source_kind,
                    "content_sha256": source.content_sha256,
                    "locator_sha256": hashlib.sha256(source.locator.encode()).hexdigest(),
                } for source in row[3]],
            } for row in rechecked],
            "target_ids": [row[0].id for row in rechecked],
            "status": "failed" if error else "completed",
            "error_type": type(error).__name__ if error else None,
            "failure_reason": getattr(error, "failure_reason", None),
            "native_dispatch": "refused_before_transport" if refused else "attempted",
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
                (error and not results and not attempts and not refused)
                or any(value.get("model_dispatched") and not value.get("usage") for value in attempts)
                or any(getattr(value, "total_tokens", None) is None for value in results)
            ),
        }, sort_keys=True))

    heartbeat()
    task = asyncio.create_task(asyncio.to_thread(
        getattr(provider, phase), manifest,
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
    return verification_result


async def _verify_source_backed_rechecks(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    rechecked: list[DreamRecheckRow],
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
                "target_snapshot": _entry_version_snapshot(entry),
                "scope_text": dream_scope_text(entry),
                "scope_partition_boundaries": ([] if entry.source_report is not None else [len(entry.title) + 1]),
                "source_kind": validation.evidence_basis,
                **({"source_report": entry.source_report.model_dump(mode="json")}
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
            for index, row in enumerate(rechecked)
            for entry, validation, reopened, sources in [row[:4]]
        ],
    }
    verification_result = await _run_dream_provider_call(
        backend, provider=provider, phase="verify", manifest=verification_manifest,
        rechecked=rechecked, deadline=deadline, receipts=receipts,
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
    checked: dict[str, Any] = {}
    for index, row in enumerate(rechecked):
        point = by_index[index]
        # v9 classification is not a proposal or a final-output attestation.
        # A schema-valid legacy fused response leaves this point unresolved.
        fused = bool(point.replacement_items or point.replacement_target_ids
                     or point.report_outputs or point.report_omissions
                     or point.output_verifications or point.update_meaning_judgment)
        point = point.model_copy(update={
            "replacement_items": [], "replacement_target_ids": [],
            "report_outputs": [], "report_omissions": [], "output_verifications": [],
            "report_preservation_inventory": None,
            "update_meaning_judgment": None,
            **({"scope_segments": [], "claim_units": [], "future_scope": "unclear",
                "source_use": "unclear", "reason": "Dream classification returned forbidden proposal or final-judgment fields."}
               if fused else {}),
        })
        scope = verification_scope_status(point, dream_scope_text(row[0]))
        if scope not in {"source_scope_durable", "source_scope_session_only"}:
            point = point.model_copy(update={"future_scope": "unclear"})
        elif scope == "source_scope_session_only":
            point = point.model_copy(update={"future_scope": "session_only"})
        checked[row[0].id] = point
    return checked


def _normalize_dream_proposal_groups(
    prepared: SeparatedPreparedAssimilation, decision: AssimilationDecision, *,
    identities: Mapping[str, str], groups: Sequence[Sequence[str]],
    report_ids: set[str], receipts: list[str] | None,
    mutable_target_ids: set[str] | None = None,
    repair_feedback: list[dict[str, Any]] | None = None,
    blocked_candidate_ids: set[str] | None = None,
    consolidation_groups: Sequence[Sequence[str]] = (),
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Isolate original comparison groups without accepting independent judgments.

    All survivors still pass the complete common validator and later final-scope
    checks. Copies are required because report normalization may mutate points.
    """
    expected = set(prepared.eligible_candidate_ids)
    # This operation comes from the original runtime signals, never model
    # fields or a provider-mutated manifest. Ordinary refinement can split.
    consolidation_targets = [set(group) for group in consolidation_groups]

    def diagnostics(points: Sequence[Any]) -> list[dict[str, Any]]:
        return [{
            "candidate_id": point.candidate_id if point.candidate_id in expected else None,
            "disposition": str(point.disposition),
            "handle_count": len(point.matched_truth_handles),
            "known_handle_count": sum(handle in prepared.truth_by_handle
                                      for handle in point.matched_truth_handles),
        } for point in points]

    def rejected(code: str, exc: ValueError, points: Sequence[Any]) -> None:
        if blocked_candidate_ids is not None:
            blocked_candidate_ids.update(str(point.candidate_id) for point in points
                if point.candidate_id in expected and str(point.disposition) in {"refine", "replace"})
        if receipts is not None:
            receipts.append("dream proposal rejected: " + json.dumps({
                "code": code, "points": diagnostics(points),
                "failure_details": exception_locations(exc),
            }, sort_keys=True))

    def validated_payloads(local: SeparatedPreparedAssimilation, proposed: AssimilationDecision):
        normalized = validate_separated_assimilation_decision(copy.deepcopy(local), copy.deepcopy(proposed))
        payloads = []
        for point in normalized["points"]:
            own_id = next(identity for identity, candidate_id in identities.items()
                          if candidate_id == point["candidate_id"])
            merge_groups = [group for group in consolidation_targets if own_id in group]
            if merge_groups:
                output_count = len(point.get("knowledge_items") or [])
                if not output_count and point.get("canonical_title") and point.get("canonical_statement"):
                    output_count = 1
                if point["disposition"] in {"no_write", "defer"}:
                    # A safe abstention must not fall back to a positive old
                    # classification and perform a different duplicate action.
                    if blocked_candidate_ids is not None:
                        blocked_candidate_ids.add(str(point["candidate_id"]))
                elif (point["disposition"] not in {"refine", "replace"}
                      or set(point["matched_truth_ids"]) not in merge_groups
                      or output_count != 1):
                    raise ValueError("duplicate consolidation requires one complete group output or safe abstention")
            if point["disposition"] not in {"refine", "replace"}:
                continue
            if own_id not in point["matched_truth_ids"]:
                raise ValueError("Dream proposal must replace its own original entry")
            if not any(own_id in group and set(point["matched_truth_ids"]).issubset(group) for group in groups):
                raise ValueError("Dream replacement must retain one complete original comparison group")
            if any(identity not in prepared.truth_by_handle.values() for identity in point["matched_truth_ids"]):
                raise ValueError("Dream proposal crosses the verified source batch")
            if mutable_target_ids is not None and not set(point["matched_truth_ids"]).issubset(mutable_target_ids):
                raise ValueError("Dream repair may not expand its original rejected mutation targets")
            if own_id in report_ids and not point.get("report_split"):
                raise ValueError("Dream report proposal requires typed retained outputs")
            payloads.append((point, final_scope_payload(local, point)))
        return payloads

    points = list(decision.points)
    try:
        candidate_ids = [str(point.candidate_id) for point in points]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Dream proposal contains duplicate candidate ids")
        if set(candidate_ids) != expected or any(
            handle not in prepared.truth_by_handle for point in points for handle in point.matched_truth_handles
        ):
            # Keep the common owner's exact failure location for malformed
            # coverage and unavailable handles, before any group is salvaged.
            validate_separated_assimilation_decision(copy.deepcopy(prepared), copy.deepcopy(decision))
            raise ValueError("Dream proposal has invalid coverage or unavailable handles")
        if any(not any(identity in group for group in groups) for identity in identities):
            raise ValueError("Dream proposal owner has no original comparison group")
        if any(len(group) < 2 or len(group) != len(set(group))
               or set(group) not in [set(original) for original in groups]
               or not set(group).issubset(prepared.truth_by_handle.values())
               for group in consolidation_groups):
            raise ValueError("Dream duplicate consolidation group changed")
    except ValueError as exc:
        rejected("common_normalization_failed", exc, points)
        return []

    # Overlapping original groups share one safety component. References across
    # independent groups taint every connected group; never trim their targets.
    parent = {identity: identity for identity in prepared.truth_by_handle.values()}

    def root(identity: str) -> str:
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    def union(left: str, right: str) -> None:
        parent[root(right)] = root(left)

    for group in groups:
        members = [identity for identity in group if identity in parent]
        for identity in members[1:]:
            union(members[0], identity)
    original_roots = {identity: root(identity) for identity in parent}
    own_by_candidate = {candidate: identity for identity, candidate in identities.items()}
    cross_edges = []
    for point in points:
        own_id = own_by_candidate[point.candidate_id]
        for handle in point.matched_truth_handles:
            target = prepared.truth_by_handle[handle]
            if original_roots[own_id] != original_roots[target]:
                cross_edges.append((own_id, target))
                union(own_id, target)
    blocked_components = {root(left) for left, _right in cross_edges}
    components: dict[str, list[Any]] = {}
    for point in points:
        components.setdefault(root(own_by_candidate[point.candidate_id]), []).append(point)
    survivors = []
    errors: list[ValueError] = []
    for component, members in components.items():
        try:
            if component in blocked_components:
                raise ValueError("Dream proposal references another original comparison group")
            local_ids = tuple(str(point.candidate_id) for point in members)
            local = replace(prepared, candidate_ids=local_ids, eligible_candidate_ids=local_ids,
                            automatic_points=())
            validated_payloads(local, decision.model_copy(update={"points": copy.deepcopy(members)}))
        except ValueError as exc:
            errors.append(exc)
            rejected("comparison_group_normalization_failed", exc, members)
            # Only an already bound original component is eligible for a
            # corrective proposal. Invalid coverage/handles and cross-group
            # references never acquire a new mutation scope through feedback.
            if repair_feedback is not None and component not in blocked_components:
                reason = {
                    "report output dropped a qualifier from its own body": "report_output_qualifier_missing",
                    "report outputs do not equal the exact temporary-omission projection": "report_literal_projection_mismatch",
                    "report output verification does not cover its title, body, and attribution": "report_rendered_scope_mismatch",
                    "duplicate consolidation requires one complete group output or safe abstention": "duplicate_consolidation_incomplete",
                }.get(str(exc), "proposal_normalization_failed")
                for point in members:
                    if str(point.disposition) not in {"refine", "replace"}:
                        continue
                    own_id = own_by_candidate[point.candidate_id]
                    targets = {prepared.truth_by_handle[handle] for handle in point.matched_truth_handles}
                    if own_id not in targets or not any(
                        own_id in group and targets.issubset(group) for group in groups
                    ):
                        continue
                    if mutable_target_ids is not None and not targets.issubset(mutable_target_ids):
                        continue
                    merge_scope = next((group for group in consolidation_targets
                                        if own_id in group and targets.issubset(group)), None)
                    repair_feedback.append({
                        "candidate_id": str(point.candidate_id),
                        "proposed_point": point.model_dump(mode="json"),
                        "allowed_target_ids": sorted(merge_scope if merge_scope is not None else targets),
                        "final_judgments": None,
                        "reason_code": reason,
                    })
            survivors.extend(point.model_copy(update={
                "disposition": "defer", "matched_truth_handles": [],
                "canonical_title": None, "canonical_statement": None, "topic_path": [],
                "knowledge_items": [], "report_topic_judgment": None,
                "report_outputs": [], "report_omissions": [], "retained_conditions": [],
                "undecided_state": None, "update_meaning_judgment": None,
                "reason": "Original comparison group proposal failed structural safety checks.",
            }, deep=True) for point in members)
        else:
            survivors.extend(copy.deepcopy(members))
    try:
        # Full coverage, authority and cross-target checks remain authoritative.
        payloads = validated_payloads(prepared, decision.model_copy(update={"points": survivors}, deep=True))
    except ValueError as exc:
        rejected("common_normalization_failed", exc, points)
        return []
    if not payloads and errors:
        rejected("common_normalization_failed", errors[0], points)
    return payloads


async def _complete_dream_proposals(
    backend: LocalMemoryBackend, *, project_name: str, rechecked: Sequence[Any],
    provider: Any, checked: dict[str, Any], receipts: list[str] | None = None,
    comparison_groups: Sequence[Sequence[str]] | None = None,
    run_id: str | None = None,
    _proposal_repair: Mapping[str, Any] | None = None,
    _repair_candidate_ids: set[str] | None = None,
    reassess_ids: set[str] | None = None,
    consolidation_groups: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    """Propose unresolved updates, then independently verify their actual payloads.

    The original support verdict remains unchanged. Proposals have no authority
    until the common final-output and whole-update checks accept them.
    """
    consolidation_groups = tuple(tuple(group) for group in consolidation_groups)
    compared_ids = {identity for group in comparison_groups or [] if len(group) > 1 for identity in group}
    selected_again = compared_ids | (reassess_ids or set())
    eligible = [row for row in rechecked if (
        (_repair_candidate_ids is None or row[0].id in _repair_candidate_ids)
        and
        checked[row[0].id].semantic_support in {"supported", "partial", "contradicted"}
        and checked[row[0].id].literal_edit_contract is None
        and checked[row[0].id].scope_segments
        and (checked[row[0].id].semantic_support == "contradicted" or any(
                part.source_support == "supported" and part.future_scope == "durable"
                and part.source_use in {"standing_decision", "reusable_knowledge", "explicit_undecided"}
                and part.content_role == "claim"
                for part in checked[row[0].id].scope_segments))
        and "".join(part.text for part in checked[row[0].id].scope_segments) == dream_scope_text(row[0])
        and not checked[row[0].id].replacement_items
        and not checked[row[0].id].report_outputs
        and (row[0].id in selected_again
             or _rendered_report_confirmation_feedback(row[0], checked[row[0].id]) is not None
             or checked[row[0].id].semantic_support != "supported"
             or verification_scope_status(checked[row[0].id], dream_scope_text(row[0]))
             not in {"source_scope_durable", "source_scope_session_only"})
    )]
    if not eligible:
        return checked
    classification_checked = copy.deepcopy(checked)
    identities = {row[0].id: (str(uuid5(NAMESPACE_URL,
        f"harness-mem:dream-candidate:{run_id}:{row[0].id}"))
        if run_id is not None and row[0].source_report is not None else f"dream:{row[0].id}")
        for row in eligible}
    groups = [list(group) for group in comparison_groups or [[row[0].id for row in rechecked]]]
    handles = {f"K{index + 1}": row[0].id for index, row in enumerate(rechecked)}
    truth = [{"handle": handle, **_entry_version_snapshot(row[0])}
             for (handle, identity), row in zip(handles.items(), rechecked)]
    source_excerpts: dict[str, dict[str, Any]] = {}
    source_refs: dict[str, list[str]] = {}
    for row in rechecked:
        source_refs[row[0].id] = []
        for source in _dream_reopened_source_rows(row):
            key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
            source_excerpts[key] = source
            source_refs[row[0].id].append(key)
    manifest = {
        "contract_version": "separated-knowledge-assimilation-v1",
        "final_scope_required": True,
        "project_name": project_name,
        "current_modules": sorted({row[0].module_path[0] for row in eligible if row[0].module_path}),
        "current_truth": truth,
        "comparison_groups": groups,
        **({"duplicate_consolidation_groups": [list(group) for group in consolidation_groups]}
           if consolidation_groups else {}),
        "source_excerpts": source_excerpts,
        "verified_candidates": [{
            "candidate_id": identities[row[0].id], "kind": "memory",
            "statement": row[0].statement, "answer_status": "ANSWERED",
            "evidence_basis": row[1].evidence_basis, "verification_reason_codes": [],
            "semantic_support": _report_proposal_support(row[0], checked[row[0].id]),
            **({"source_report": row[0].source_report.model_dump(mode="json")}
               if row[0].source_report is not None else {}),
        } for row in eligible],
        "maintenance_candidates": [{
            "candidate_id": identities[row[0].id],
            "target_snapshot": _entry_version_snapshot(row[0]),
            "scope_text": dream_scope_text(row[0]),
            "scope_verification": checked[row[0].id].model_dump(mode="json"),
            "source_refs": source_refs[row[0].id],
            **({"rendered_confirmation_feedback": feedback}
               if (feedback := _rendered_report_confirmation_feedback(row[0], checked[row[0].id]))
               is not None else {}),
        } for row in eligible],
    }
    report_revision_modes = {
        identities[row[0].id]: "source_backed_same_topic_revision"
        for row in eligible if row[0].source_report is not None
    }
    if selected_again or report_revision_modes:
        manifest["maintenance_purpose"] = {
            "kind": "source_backed_reassessment",
            "instruction": (
                "A supported current sentence does not establish that related current entries are distinct "
                "or that the same original source's still-applicable conditions were preserved. Compare the "
                "complete selected groups and original evidence. Consolidate semantic overlaps, keeping "
                "independent facts separate. For the selected existing report topics, restore any same-topic "
                "source-supported diagnostic evidence or necessary qualifier missing from the current account, "
                "while preserving its original speaker, period and evidence boundary. Remove only genuinely "
                "temporary context. Do not invent a claim, borrow another speaker's authority or rewrite "
                "merely to shorten text. A no-write decision remains valid when nothing requires correction. "
                "All proposed final content still requires independent source and whole-update verification."
            ),
        }
        # Source rechecking has already reopened every cited exchange. The
        # runtime grants this same-topic proposal mode; model output cannot
        # turn a literal cleanup or an ordinary fact into a report revision.
        if report_revision_modes:
            manifest["report_revision_modes"] = report_revision_modes
    if _proposal_repair is not None:
        manifest["proposal_repair"] = copy.deepcopy(dict(_proposal_repair))
    prepared = SeparatedPreparedAssimilation(
        project_name=project_name, project_root=str(backend.data_dir),
        candidate_ids=tuple(identities.values()), eligible_candidate_ids=tuple(identities.values()),
        automatic_points=(), answer_status_by_candidate={value: "ANSWERED" for value in identities.values()},
        truth_by_handle=handles, manifest=manifest,
    )
    proposed = await _run_dream_provider_call(
        backend, provider=provider, phase="assimilate", manifest=manifest,
        rechecked=eligible, receipts=receipts,
    )
    if not isinstance(proposed.decision, AssimilationDecision):
        raise ProviderError("Dream proposal returned an unexpected decision", kind="unrecoverable")
    rejected_proposals: list[dict[str, Any]] = []
    structurally_blocked: set[str] = set()
    payloads = _normalize_dream_proposal_groups(
        prepared, proposed.decision, identities=identities, groups=groups,
        report_ids={row[0].id for row in eligible if row[0].source_report is not None},
        receipts=receipts,
        mutable_target_ids=(set(_proposal_repair["allowed_target_ids"])
                            if _proposal_repair is not None else None),
        repair_feedback=rejected_proposals,
        blocked_candidate_ids=structurally_blocked,
        consolidation_groups=consolidation_groups,
    )
    for blocked_owner in structurally_blocked:
        identity = next(identity for identity, owner in identities.items()
                        if owner == blocked_owner)
        # Failed structural proposals cannot fall back to deletion or an old
        # positive classification when a correction is unavailable/nonwriting.
        checked[identity] = checked[identity].model_copy(update={
            "scope_segments": [], "claim_units": [], "future_scope": "unclear",
            "output_verifications": [], "update_meaning_judgment": None,
        })
    final_rows: list[dict[str, Any]] = []
    rows_by_owner: dict[str, list[dict[str, Any]]] = {}
    by_id = {row[0].id: row for row in rechecked}
    proposals = {point.candidate_id: point for point in proposed.decision.points}
    for point, payload in payloads:
        owner = str(point["candidate_id"])
        identity = next(identity for identity, candidate_id in identities.items() if candidate_id == owner)
        # Retain an unaccepted proposal as an explicit blocked write. If its
        # final check fails, the planner must not fall back to retiring an old
        # contradicted row as though no replacement had been proposed.
        proposal_fields: dict[str, Any] = {
            "claim_units": [], "output_verifications": [], "update_meaning_judgment": None,
        }
        if payload.get("report_preservation_inventory") is not None:
            proposal_fields["report_preservation_inventory"] = payload["report_preservation_inventory"]
        if point.get("report_split"):
            proposal_fields.update(report_outputs=list(proposals[owner].report_outputs),
                                   report_omissions=list(proposals[owner].report_omissions))
        else:
            proposal_fields.update(replacement_items=[CanonicalKnowledgeItem.model_validate(item)
                for item in payload["knowledge_items"]], replacement_target_ids=list(point["matched_truth_ids"]))
        checked[identity] = checked[identity].model_copy(update=proposal_fields)
        sources = []
        for target in payload["targets"]:
            row = by_id[str(target["id"])]
            sources.extend(_dream_reopened_source_rows(row))
        rows = final_scope_verification_rows(payload, sources)
        for row in rows:
            if any(set(point["matched_truth_ids"]) == set(group) for group in consolidation_groups):
                row["update_context"]["maintenance_operation"] = {
                    "kind": "duplicate_consolidation", "target_ids": list(point["matched_truth_ids"]),
                    "required_outputs": 1,
                }
            row["candidate_index"] = len(final_rows)
            final_rows.append(row)
        rows_by_owner[str(point["candidate_id"])] = rows
    decision = CandidateVerificationDecision(points=[])
    if final_rows:
        result = await _run_dream_provider_call(
            backend, provider=provider, phase="verify",
            manifest={"contract_version": "final-knowledge-scope-v1", "scope_partition_required": True,
                      "project_name": project_name, "candidates": final_rows},
            rechecked=rechecked, receipts=receipts,
        )
        decision = result.decision
    if (not isinstance(decision, CandidateVerificationDecision)
            or len(decision.points) != len(final_rows)
            or {point.candidate_index for point in decision.points} != set(range(len(final_rows)))):
        raise ProviderError("Dream final verification must cover every exact output", kind="unrecoverable")
    verdicts = {point.candidate_index: point for point in decision.points}
    accepted_targets: set[str] = set()
    for point, payload in payloads:
        owner = str(point["candidate_id"])
        rows = rows_by_owner[owner]
        stamped, blocked = judged_update_payload(payload, decision, rows)
        local = CandidateVerificationDecision(points=[
            verdicts[row["candidate_index"]].model_copy(update={"candidate_index": index})
            for index, row in enumerate(rows)
        ])
        try:
            if blocked:
                raise ValueError(blocked)
            prove_supplied_final_scope(payload=stamped, judgment=local)
        except ValueError as exc:
            rejected_proposals.append({
                "candidate_id": owner,
                "payload": copy.deepcopy(payload),
                "final_judgments": local.model_dump(mode="json"),
                "reason_code": blocked or "final_scope_judgment_rejected",
            })
            if receipts is not None:
                receipts.append("dream proposal rejected: " + json.dumps({
                    "code": "final_scope_or_meaning_failed",
                    "candidate_id": owner,
                    "reason_code": blocked or "final_scope_judgment_rejected",
                    "failure_details": exception_locations(exc),
                }, sort_keys=True))
            continue
        identity = next(identity for identity, candidate_id in identities.items() if candidate_id == owner)
        proposal = proposals[owner]
        updates = {
            "literal_edit_contract": None,
            "claim_units": [],
            "update_meaning_judgment": local.points[0].update_meaning_judgment,
            "output_verifications": [OutputVerification.model_validate({
                key: getattr(verdict, key) for key in OutputVerification.model_fields
            }) for verdict in local.points],
        }
        if stamped.get("report_preservation_inventory") is not None:
            updates["report_preservation_inventory"] = stamped["report_preservation_inventory"]
        if point.get("report_split"):
            updates.update(report_outputs=list(proposal.report_outputs), report_omissions=list(proposal.report_omissions))
        else:
            updates.update(replacement_items=[CanonicalKnowledgeItem.model_validate(item)
                for item in payload["knowledge_items"]], replacement_target_ids=list(point["matched_truth_ids"]))
        checked[identity] = checked[identity].model_copy(update=updates)
        accepted_targets.update(str(target["id"]) for target in payload["targets"])
    if rejected_proposals and _proposal_repair is None:
        # One bounded revision uses the same proposal/final owners, source
        # snapshots and cumulative task account. A rejected label is feedback,
        # never deletion authority or permission to overwrite an accepted group.
        rejected_ids = {identity for identity, owner in identities.items()
                        if any(item["candidate_id"] == owner for item in rejected_proposals)}
        available = {row[0].id for row in rechecked}
        repair_ids: set[str] = set()
        for identity in sorted(rejected_ids):
            component = {identity}
            changed = True
            while changed:
                expanded = component | {member for group in groups if component.intersection(group)
                                        for member in group}
                changed = expanded != component
                component = expanded
            if not component.issubset(available) or component.intersection(accepted_targets):
                continue
            repair_ids.update(component)
        # Keep the actual original groups. Their connected components decide
        # isolation, but are not broader permission to merge across groups.
        repair_groups = [list(group) for group in groups if set(group).issubset(repair_ids)]
        failed_owners = {identities[identity] for identity in rejected_ids.intersection(repair_ids)}
        feedback = [item for item in rejected_proposals if item["candidate_id"] in failed_owners]
        if feedback:
            allowed_targets = {identity for item in feedback for identity in (
                item.get("allowed_target_ids") or
                [str(target["id"]) for target in item["payload"]["targets"]]
            )}
            repair_manifest = {"attempt": 1, "allowed_target_ids": sorted(allowed_targets),
                               "previous_rejections": feedback}
            if receipts is not None:
                receipts.append("dream proposal repair: " + json.dumps({
                    "attempt": 1, "candidate_ids": sorted(failed_owners),
                    "comparison_groups": repair_groups,
                }, sort_keys=True))
            try:
                repaired = await _complete_dream_proposals(
                    backend, project_name=project_name,
                    rechecked=rechecked,
                    provider=provider,
                    checked=classification_checked,
                    receipts=receipts, comparison_groups=groups,
                    run_id=run_id,
                    _proposal_repair=repair_manifest,
                    _repair_candidate_ids=rejected_ids.intersection(repair_ids),
                    reassess_ids=reassess_ids,
                    consolidation_groups=consolidation_groups,
                )
            except ProviderError as exc:
                # Existing provider receipts retain the failed call/real usage;
                # its original budget blocks any later forbidden dispatch. An
                # unavailable revision cannot erase earlier accepted evidence.
                if receipts is not None:
                    receipts.append("dream proposal repair unavailable: " + json.dumps({
                        "attempt": 1, "error_type": type(exc).__name__, "kind": exc.kind,
                    }, sort_keys=True))
            else:
                for identity, point in repaired.items():
                    if point.output_verifications and (point.replacement_items or point.report_outputs):
                        checked[identity] = point
                # Non-writing or rejected revisions leave the first explicit
                # blocked proposal in place; no older positive fallback.
    return checked


def _dream_reopened_source_rows(row: Any) -> list[dict[str, Any]]:
    """Project complete reopened evidence without persisting its prose."""
    return [{"kind": source.source_kind, "project_name": source.project_name,
             "content_sha256": source.content_sha256, "content": reopened.content,
             **({"role": row[0].source_report.speaker,
                 "content_scope": "native_speaker_only; attributed source report, not external current truth"}
                if row[0].source_report is not None else
                {"role": "user"} if source.source_kind == "user_statement" else {})}
            for reopened, source in zip(row[2], row[3])]


async def _verify_dream_report_confirmations(
    backend: LocalMemoryBackend, *, project_name: str, rechecked: Sequence[Any],
    provider: Any, checked: dict[str, Any], receipts: list[str] | None,
) -> dict[str, Any]:
    """A report-body classification cannot attest its final rendered authority."""
    selected = [row for row in rechecked if row[0].source_report is not None
        and checked[row[0].id].semantic_support == "supported"
        and not checked[row[0].id].output_verifications
        and not checked[row[0].id].report_outputs
        and not checked[row[0].id].replacement_items
        and verification_scope_status(checked[row[0].id], dream_scope_text(row[0])) == "source_scope_durable"]
    if not selected:
        return checked
    rows = []
    for row in selected:
        sources = _dream_reopened_source_rows(row)
        payload = {"candidate_id": row[0].id, "disposition": "confirm", "knowledge_items": [],
                   "targets": [_entry_version_snapshot(row[0])]}
        final_row = final_scope_verification_rows(payload, sources)[0]
        final_row["candidate_index"] = len(rows)
        rows.append(final_row)
    result = await _run_dream_provider_call(
        backend, provider=provider, phase="verify", rechecked=selected, receipts=receipts,
        manifest={"contract_version": "final-knowledge-scope-v1", "scope_partition_required": True,
                  "project_name": project_name, "candidates": rows},
    )
    decision = result.decision
    if (not isinstance(decision, CandidateVerificationDecision) or len(decision.points) != len(rows)
            or {point.candidate_index for point in decision.points} != set(range(len(rows)))):
        raise ProviderError("Dream report confirmation requires every final output", kind="unrecoverable")
    by_index = {point.candidate_index: point for point in decision.points}
    for index, row in enumerate(selected):
        verdict = by_index[index]
        checked[row[0].id] = checked[row[0].id].model_copy(update={"output_verifications": [
            OutputVerification.model_validate({key: getattr(verdict, key) for key in OutputVerification.model_fields})
        ]})
    return checked


def _rendered_report_confirmation_feedback(entry: KnowledgeEntry, point: Any) -> dict[str, Any] | None:
    """Keep an independently failed rendered judgment as feedback, not a source."""
    if (entry.source_report is None or len(point.output_verifications) != 1
            or point.report_outputs or point.replacement_items):
        return None
    verdict = point.output_verifications[0]
    scope = report_output_scope_text(entry.source_report)
    judgment = CandidateVerificationDecision(points=[CandidateVerificationPoint.model_validate({
        "candidate_index": 0, **verdict.model_dump(mode="json"),
    })])
    blocked = bind_final_scope_judgment(
        [{"owner_candidate_id": entry.id, "scope_text": scope}], judgment,
    )
    if not blocked:
        return None
    return {"kind": "runtime_rendered_confirmation_not_source_evidence",
            "instruction": "This independent failed judgment is proposal feedback, not source evidence. "
                           "Reopen the original report account and retain every applicable qualifier; "
                           "do not upgrade partial support or treat feedback as a new user statement.",
            "scope_text_sha256": hashlib.sha256(scope.encode()).hexdigest(),
            "reason_code": blocked[entry.id], "judgment": verdict.model_dump(mode="json")}


def _report_proposal_support(entry: KnowledgeEntry, point: Any) -> str:
    """A negative rendered source verdict cannot become whole report support."""
    original = point.semantic_support
    feedback = _rendered_report_confirmation_feedback(entry, point)
    if original == "supported" and feedback is not None:
        rendered = feedback["judgment"]["semantic_support"]
        if rendered != "supported":
            return rendered
    return original


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
    recheck_cache: list[DreamRecheckRow] | None = None,
    source_skip_cache: dict[str, tuple[str, str]] | None = None,
    verification_cache: dict[str, Any] | None = None,
    receipts: list[str] | None = None,
    proposals_prepared: bool = False,
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

    # Classification checkpoints contain no proposal prose. Form, verify and
    # commit proposals within this original comparison group before yielding.
    if not proposals_prepared:
        verification_by_id = await _verify_dream_report_confirmations(
            backend, project_name=project_name, rechecked=rechecked, provider=provider,
            checked=dict(verification_by_id), receipts=receipts,
        )
        verification_by_id = await _complete_dream_proposals(
            backend, project_name=project_name, rechecked=rechecked, provider=provider,
            checked=dict(verification_by_id), receipts=receipts,
            run_id=run_id,
            comparison_groups=[signal.target_ids],
            consolidation_groups=[signal.target_ids] if signal.kind == "duplicate" else (),
        )

    prepared = prepare_dream_assimilation(
        project_name=project_name,
        project_root=project_root,
        run_id=run_id,
        signal_kind=signal.kind,
        candidates=[
            DreamAssimilationCandidate(
                candidate_id=(str(uuid5(NAMESPACE_URL,
                    f"harness-mem:dream-candidate:{run_id}:{entry.id}"))
                    if verification_by_id[entry.id].report_preservation_inventory is not None else str(
                    uuid5(
                        NAMESPACE_URL,
                        "harness-mem:dream-recheck:"
                        f"{run_id}:{signal.kind}:{entry.id}:{signal.cause_id or ''}",
                    )
                )),
                entry=entry,
                sources=effective_sources,
                original_sources=row[4] if len(row) > 4 else None,
                semantic_support=verification_by_id[entry.id].semantic_support,
                future_scope=verification_by_id[entry.id].future_scope,
                verification_reason=verification_by_id[entry.id].reason,
                scope_verification=verification_by_id[entry.id],
                verification_contract=DREAM_SOURCE_RECHECK_CONTRACT,
                source_excerpts=(),
            )
            for row in rechecked
            for entry, _validation, reopened, effective_sources in [row[:4]]
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
    if status == "failed":
        return DreamItem(
            source_kind=source_kind,
            source_id=str(outcome["entry_id"]),
            risk=signal.risk,
            proposed_action=signal.proposed_action,
            final_action="failed",
            reason=str(outcome.get("reason") or "Dream maintenance failed."),
            result={"truth_change": "none"},
            error=str(outcome.get("reason") or "Dream maintenance failed."),
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


def _legacy_dream_accounting(
    backend: LocalMemoryBackend, run: DreamRun, *, project_root: str | Path | None,
    host_client: str,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Recover one exact old source account and its recorded Dream calls."""
    from harness_mem.autonomous.worker import read_autonomous_receipt
    from harness_mem.autonomous.executors.task_budget import TaskBudgetRefusal

    def refuse() -> None:
        raise TaskBudgetRefusal("legacy Dream accounting cannot be linked completely",
                                code="remaining_not_demonstrable", kind="budget")

    def metadata_known(value: Mapping[str, Any]) -> bool:
        return (all(value.get(key, host_client) == host_client for key in ("host_client", "client"))
                and all(value.get(key, 0) == 0 for key in (
                    "unknown_attempt_count", "unknown_native_call_usage_count",
                    "unknown_response_usage_count", "unknown_usage_count",
                )) and value.get("usage_unknown", False) is False)

    def usage_totals(value: Mapping[str, Any]) -> tuple[int, int, int]:
        amounts = tuple(value.get(key) for key in ("input_tokens", "output_tokens", "total_tokens"))
        if (any(type(amount) is not int or amount < 0 for amount in amounts)
                or amounts[2] != amounts[0] + amounts[1]):
            refuse()
        return cast(tuple[int, int, int], amounts)

    prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
    jobs = {note[len(prefix):].strip() for note in run.notes for prefix in prefixes
            if note.startswith(prefix)}
    if len(jobs) != 1 or project_root is None:
        refuse()
    job_id = next(iter(jobs))
    job = backend.transcript_store.get_distill_job(job_id)
    receipt = read_autonomous_receipt(Path(backend.data_dir), project_name=run.project_name,
                                      project_root=Path(project_root)) or {}
    completion = receipt.get("last_verified_completion") or {}
    provider = completion.get("provider") or {}
    if (job is None or job.id != job_id or job.project_name != run.project_name or job.status != "completed"
            or str(Path(job.project_root).resolve()) != str(Path(project_root).resolve())
            or job.client != host_client or completion.get("client") != host_client
            or completion.get("job_id") != job_id or provider.get("job_id") != job_id
            or completion.get("session_id") != job.session_id
            or completion.get("trigger_id") != job.session_id
            or provider.get("source_revision") != job.source_revision
            or provider.get("host_client") != host_client
            or provider.get("unknown_native_call_usage_count") != 0
            or not metadata_known(provider)
            or not completion.get("dispatch_generation")):
        refuse()
    native = provider.get("native_attempts")
    if not isinstance(native, list) or not native:
        refuse()
    calls = [{**row, "phase": "source"} for row in native if isinstance(row, dict)]
    if len(calls) != len(native):
        refuse()
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in calls:
        if (not metadata_known(row)
                or row.get("source_revision", job.source_revision) != job.source_revision
                or row.get("job_id", job_id) != job_id):
            refuse()
        usage_totals(row.get("usage") or {})
        call_id = row.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            refuse()
        prior = deduplicated.get(call_id)
        if prior is not None and any(prior.get(key) != row.get(key) for key in (
            "usage", "duration_seconds", "unknown_response_usage_count", "status", "model_dispatched",
        )):
            refuse()
        deduplicated[call_id] = row
    calls = list(deduplicated.values())
    if provider.get("attempt_count") != len(calls):
        refuse()
    # Aggregate fields independently bind the complete source-account list.
    usage_totals(provider)
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        amounts = [(row.get("usage") or {}).get(field) for row in calls]
        if any(type(value) is not int or value < 0 for value in amounts):
            refuse()
        if sum(amounts) != provider.get(field):
            refuse()
    dream_calls: list[dict[str, Any]] = []
    verified_targets: set[str] = set()
    receipt_count = 0
    for note in run.notes:
        if not note.startswith("dream verification receipt: "):
            continue
        try:
            recorded = json.loads(note.split(": ", 1)[1])
        except (ValueError, TypeError):
            refuse()
        if recorded.get("usage_unknown") is not False or not isinstance(recorded.get("native_attempts"), list):
            refuse()
        if not metadata_known(recorded) or not recorded["native_attempts"]:
            refuse()
        results = recorded.get("results")
        targets = recorded.get("target_ids")
        if (not isinstance(results, list) or not results or not isinstance(targets, list)
                or not targets or any(not isinstance(target, str) for target in targets)):
            refuse()
        native_rows: dict[str, Mapping[str, Any]] = {}
        for row in recorded["native_attempts"]:
            if not isinstance(row, dict) or not metadata_known(row) or not isinstance(row.get("call_id"), str):
                refuse()
            usage_totals(row.get("usage") or {})
            prior = native_rows.get(row["call_id"])
            if prior is not None and prior != row:
                refuse()
            native_rows[row["call_id"]] = row
        expected_totals = tuple(sum(usage_totals(row.get("usage") or {})[index]
                                    for row in native_rows.values()) for index in range(3))
        result_totals = tuple(sum(usage_totals(row)[index] for row in results) for index in range(3))
        if expected_totals != result_totals or any(not metadata_known(row) for row in results):
            refuse()
        verified_targets.update(targets)
        receipt_count += 1
        dream_calls.extend({**row, "phase": "dream"} for row in native_rows.values())
    verification = run.continuation.get("verification") or {}
    completed_indexes = run.continuation.get("completed_signal_indexes") or []
    signals = run.continuation.get("signals") or []
    expected_targets = set(verification)
    for index in completed_indexes:
        if type(index) is not int or index < 0 or index >= len(signals):
            refuse()
        expected_targets.update(signals[index].get("target_ids") or [])
    if (expected_targets - verified_targets or (run.items and not dream_calls)
            or (run.continuation.get("slice_count", 0) > 0 and not receipt_count)):
        refuse()
    return ({"trigger_id": str(completion["trigger_id"]),
             "dispatch_generation": str(completion["dispatch_generation"])}, calls + dream_calls)


async def _freeze_explicit_repair_scope(
    backend: Any, *, project_name: str, project_root: str | Path,
    run_id: str, scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze an explicitly requested maintenance scope, without supplying prose."""
    from harness_mem.commands.dream_source_coverage import _digest, prepare_explicit_source_repair

    if not isinstance(scope, Mapping) or set(scope) - {"source", "groups"}:
        raise ValueError("dream_repair_scope_invalid")
    groups = scope.get("groups")
    if not isinstance(groups, list) or len(groups) > 200:
        raise ValueError("dream_repair_groups_invalid")
    frozen, seen = [], set()
    for group in groups:
        if (not isinstance(group, Mapping) or set(group) != {"kind", "target_ids"}
                or group.get("kind") not in {"stale", "duplicate", "conflict"}
                or not isinstance(group.get("target_ids"), list) or not group["target_ids"]
                or any(not isinstance(identity, str) or not identity for identity in group["target_ids"])
                or len(set(group["target_ids"])) != len(group["target_ids"])
                or set(group["target_ids"]).intersection(seen)
                or (group["kind"] == "stale" and len(group["target_ids"]) != 1)
                or (group["kind"] != "stale" and len(group["target_ids"]) < 2)):
            raise ValueError("dream_repair_group_invalid")
        targets = []
        for identity in group["target_ids"]:
            entry = await backend.structured_store.knowledge_store.get_entry(
                identity, project_name=project_name, project_root=project_root)
            if entry is None or entry.project_name != project_name:
                raise ValueError("dream_repair_target_not_current")
            sources = await backend.structured_store.knowledge_store.list_sources(identity)
            if not sources:
                raise ValueError("dream_repair_target_source_missing")
            targets.append({"id": identity, "fingerprint": _scope_fingerprint(entry),
                "sources_sha256": _digest([row.to_dict() for row in sources])})
        frozen.append({"kind": group["kind"], "target_ids": list(group["target_ids"]),
                       "targets": targets})
        seen.update(group["target_ids"])
    source = scope.get("source")
    prepared = None
    if source is not None:
        if isinstance(source, Mapping) and source.get("handoff_only") is True:
            if (set(source) != {"origin_run_id", "source_job_id", "handoff_ids", "handoff_only"}
                    or any(not isinstance(source.get(key), str) or not source[key]
                           for key in ("origin_run_id", "source_job_id"))
                    or not isinstance(source["handoff_ids"], list) or not source["handoff_ids"]
                    or any(not isinstance(key, str) or not key for key in source["handoff_ids"])
                    or len(source["handoff_ids"]) != len(set(source["handoff_ids"]))):
                raise ValueError("dream_repair_source_handoff_invalid")
            from harness_mem.commands.source_handoff_recovery import prepare_source_handoff_recovery
            prepared = await prepare_source_handoff_recovery(backend, project_name=project_name,
                project_root=project_root, run_id=run_id, origin_run_id=source["origin_run_id"],
                source_job_id=source["source_job_id"], handoff_ids=source["handoff_ids"])
        elif (not isinstance(source, Mapping) or set(source) - {"clarification_context"} not in (
                {"origin_run_id", "predecessor_ids"}, {"origin_run_id", "predecessor_ids", "audit_only"},
                {"origin_run_id", "predecessor_ids", "audit_only", "resolved_handoff_run_id"})
                or ("audit_only" in source and source["audit_only"] is not True)
                or ("clarification_context" in source and (source.get("audit_only") is not True
                    or not isinstance(source["clarification_context"], Mapping)))
                or ("resolved_handoff_run_id" in source and (
                    not isinstance(source["resolved_handoff_run_id"], str)
                    or not source["resolved_handoff_run_id"]))
                or not isinstance(source["origin_run_id"], str)
                or not isinstance(source["predecessor_ids"], list) or not source["predecessor_ids"]):
            raise ValueError("dream_repair_source_invalid")
        elif source.get("audit_only") is True:
            from harness_mem.commands.dream_source_audit import prepare_explicit_source_audit
            prepared = await prepare_explicit_source_audit(backend, project_name=project_name,
                project_root=project_root, run_id=run_id,
                origin_run_id=source["origin_run_id"], predecessor_ids=source["predecessor_ids"],
                resolved_handoff_run_id=source.get("resolved_handoff_run_id"),
                clarification_context=source.get("clarification_context"))
        else:
            prepared = await prepare_explicit_source_repair(backend, project_name=project_name,
                project_root=project_root, run_id=run_id, **source)
    if prepared is None and not frozen:
        raise ValueError("dream_repair_scope_empty")
    return {"contract": "explicit-dream-repair-v1", "source": prepared, "groups": frozen}


async def _assert_explicit_repair_targets(
    backend: Any, *, project_name: str, project_root: str | Path,
    scope: Mapping[str, Any], completed_indexes: set[int],
) -> None:
    from harness_mem.commands.dream_source_coverage import _digest

    if scope.get("contract") != "explicit-dream-repair-v1":
        raise ValueError("dream_repair_contract_changed")
    for index, group in enumerate(scope["groups"]):
        if index in completed_indexes:
            continue
        for target in group["targets"]:
            entry = await backend.structured_store.knowledge_store.get_entry(
                target["id"], project_name=project_name, project_root=project_root)
            sources = await backend.structured_store.knowledge_store.list_sources(target["id"])
            if (entry is None or _scope_fingerprint(entry) != target["fingerprint"]
                    or _digest([row.to_dict() for row in sources]) != target["sources_sha256"]):
                raise ValueError("dream_repair_target_changed")


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
    maintenance_scope: Mapping[str, str] | None = None,
    coverage_origin_run_id: str | None = None,
    report_origin_run_id: str | None = None,
    repair_scope: Mapping[str, Any] | None = None,
) -> DreamRun:
    """Run one bounded slice; automatic callers resume the same complete ledger."""

    coverage_origin = None
    report_origin = None
    if report_origin_run_id:
        from harness_mem.commands.dream_report_continuation import bound_terminal_report_origin
        from harness_mem.hook_background import background_generation_from_env
        if (resume_run_id or coverage_origin_run_id or source != "ide_hook" or not host_client
                or not project_root or not isinstance(config, MergedConfig)
                or os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1"):
            raise ValueError("terminal_report_detached_owner_required")
        report_origin, generation, trigger, _source_job = await bound_terminal_report_origin(
            backend, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client, origin_run_id=report_origin_run_id,
            require_idle=False,
        )
        if (generation != background_generation_from_env()
                or dict(maintenance_scope or {}) != {"trigger_id": trigger, "dispatch_generation": generation}):
            raise ValueError("terminal_report_account_mismatch")
    if coverage_origin_run_id:
        from harness_mem.commands.dream_source_coverage import bound_terminal_source_coverage_origin
        from harness_mem.hook_background import background_generation_from_env
        if (resume_run_id or source != "ide_hook" or not host_client or not project_root
                or not isinstance(config, MergedConfig)
                or os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1"):
            raise ValueError("terminal_source_coverage_detached_owner_required")
        coverage_origin, generation, trigger, _source_job = await bound_terminal_source_coverage_origin(
            backend, project_name=project_name, project_root=project_root,
            config=config, host_client=host_client, origin_run_id=coverage_origin_run_id,
            require_idle=False,
        )
        if (generation != background_generation_from_env()
                or dict(maintenance_scope or {}) != {"trigger_id": trigger, "dispatch_generation": generation}):
            raise ValueError("terminal_source_coverage_account_mismatch")
    store = cast(LocalStructuredStore, backend.structured_store)
    previous = ([await store.get_dream_run(resume_run_id)] if resume_run_id else
        await store.list_dream_runs(project_name, limit=1))
    if resume_run_id and (not previous[0] or previous[0].project_name != project_name
            or previous[0].status != "continuing"):
        raise ValueError("requested Dream continuation is not resumable for this project")
    resumed = previous[0] if (coverage_origin is None and report_origin is None
        and (reflection_job_id or resume_run_id) and previous and previous[0]
        and previous[0].status == "continuing"
        and previous[0].continuation.get("version") == "dream-slices-v3") else None
    run_id = resumed.id if resumed is not None else str(uuid4())
    explicit_repair = (resumed.continuation.get("explicit_repair_scope") if resumed is not None else None)
    if repair_scope is not None:
        if (source != "agent" or resumed is not None or resume_run_id or coverage_origin_run_id
                or report_origin_run_id or reflection_job_id or project_root is None):
            raise ValueError("dream_repair_requires_explicit_fresh_agent_request")
        explicit_repair = await _freeze_explicit_repair_scope(backend, project_name=project_name,
            project_root=project_root, run_id=run_id, scope=repair_scope)
    if explicit_repair is not None and (source != "agent" or coverage_origin_run_id or report_origin_run_id):
        raise ValueError("dream_repair_cannot_be_automatic_takeover")
    selected_provider = semantic_provider
    bound_scope = dict((resumed.continuation.get("maintenance_scope") if resumed else None)
                       or maintenance_scope or {
                           "trigger_id": "dream-" + run_id,
                           "dispatch_generation": "standalone-" + run_id,
                       })
    handoff_source = (explicit_repair or {}).get("source") or (
        resumed.continuation.get("source_handoff_recovery_scope") if resumed else None)
    if isinstance(handoff_source, Mapping) and handoff_source.get("contract") == "explicit-source-handoff-recovery-v1":
        original_scope = handoff_source["binding"]["maintenance_scope"]
        if ((maintenance_scope is not None and dict(maintenance_scope) != original_scope)
                or (resumed is not None and resumed.continuation.get("maintenance_scope") != original_scope)):
            raise ValueError("source_handoff_original_account_changed")
        bound_scope = dict(original_scope)
    completed_run: DreamRun | None = None
    previous_owner_heartbeat = None
    previous_report_persist = None

    async def save_runtime_run(value: DreamRun) -> None:
        persist = getattr(selected_provider, "_dream_report_persist", None)
        if report_origin is not None or (resumed is not None
                and resumed.continuation.get("terminal_report_origin_run_id")):
            if callable(persist) and persist is not previous_report_persist:
                await persist(value)
            else:
                from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
                raise CanonicalTransactionPreconditionError("terminal_report_checkpoint_owner_missing")
        else:
            await store.save_dream_run(value)

    try:
        selected_provider = semantic_provider or _dream_provider_from_config(config, host_client=host_client)
        previous_owner_heartbeat = getattr(selected_provider, "_dream_owner_heartbeat", None)
        previous_report_persist = getattr(selected_provider, "_dream_report_persist", None)
        if callable(getattr(selected_provider, "bind_task_budget", None)):
            from harness_mem.autonomous.executors.task_budget import (
                arm_provider_maintenance_task, bind_maintenance_task,
                is_production_native_host, seed_legacy_task_budget,
            )

            if not isinstance(config, MergedConfig):
                raise ValueError("native Dream requires the explicit merged task-budget configuration")
            if (resumed is not None and not resumed.continuation.get("maintenance_scope")
                    and is_production_native_host(getattr(selected_provider, "host_client", ""))):
                bound_scope, prior_calls = _legacy_dream_accounting(
                    backend, resumed, project_root=project_root,
                    host_client=selected_provider.host_client,
                )
                legacy_binding = bind_maintenance_task(
                    data_dir=Path(backend.data_dir), host_client=selected_provider.host_client,
                    config=config, **bound_scope,
                )
                seed_legacy_task_budget(legacy_binding, calls=prior_calls, legacy_run_id=resumed.id)
                resumed.continuation["maintenance_scope"] = bound_scope
                await save_runtime_run(resumed)
            bookkeeping_only = (resumed is not None
                and resumed.continuation.get("terminal_report_origin_run_id")
                and set(resumed.continuation.get("completed_signal_indexes") or [])
                    == set(range(len(resumed.continuation.get("signals") or []))))
            ordinal = (int(resumed.continuation.get("slice_count", 0))
                       + (0 if bookkeeping_only else 1)) if resumed else 1
            arm_provider_maintenance_task(
                selected_provider, data_dir=Path(backend.data_dir), config=config,
                trigger_id=bound_scope["trigger_id"],
                dispatch_generation=bound_scope["dispatch_generation"], phase="dream",
                slice_id=f"dream:{run_id}:{ordinal}",
            )
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
            _maintenance_scope=bound_scope,
            _coverage_origin=coverage_origin,
            _report_origin=report_origin,
            _explicit_repair=explicit_repair,
        )
        return completed_run
    except _DreamSliceYield:
        completed_run = await store.get_dream_run(run_id)
        if completed_run is None or completed_run.status != "continuing":
            raise RuntimeError("Dream scheduling yield has no persisted continuation") from None
        return completed_run
    except Exception as exc:
        store = cast(LocalStructuredStore, backend.structured_store)
        run = await store.get_dream_run(run_id)
        if run is None:
            run = DreamRun(id=run_id, project_name=project_name, status="processing",
                           trigger_source=source, reflection_job_id=reflection_job_id,
                           continuation={"maintenance_scope": bound_scope})
        if run is not None and run.status == "processing":
            completed_at = _now()
            run.status = "failed"
            run.execution_status = "failed"
            source_failure = isinstance(exc, ProviderError) and getattr(exc, "_source_coverage_provider_failure", False)
            run.resolution_status = "unresolved" if source_failure else "failed"
            if source_failure:
                exc._source_coverage_run_id = run.id
                run.continuation["source_coverage_failure"] = {
                    "kind": exc.kind, "failure_reason": exc.failure_reason,
                    "bookkeeping_failure": getattr(exc, "_source_coverage_bookkeeping_failure", None),
                }
            run.completed_at = completed_at
            run.duration_ms = int(
                (completed_at - run.started_at).total_seconds() * 1000
            )
            run.notes = list(run.notes or [])
            run.notes.append(f"dream failed: {type(exc).__name__}")
            if getattr(exc, "failure_reason", None):
                run.continuation["failure_reason"] = exc.failure_reason
                run.notes.append("dream failure reason: " + exc.failure_reason)
            run.notes.append("dream failure locations: " + json.dumps(exception_locations(exc)))
            await save_runtime_run(run)
        raise
    finally:
        try:
            if callable(getattr(selected_provider, "bind_task_budget", None)):
                from harness_mem.autonomous.executors.task_budget import (
                    task_budget_observation, TASK_BUDGET_REFUSAL_CODES,
                )

                run = completed_run or await store.get_dream_run(run_id)
                if run is not None:
                    run.continuation["task_budget"] = task_budget_observation(
                        Path(backend.data_dir), bound_scope.get("trigger_id"),
                        bound_scope.get("dispatch_generation"))
                    if run.continuation.get("failure_reason"):
                        run.continuation["task_budget"]["dispatch_failure_reason"] = run.continuation["failure_reason"]
                        if run.continuation["failure_reason"] in TASK_BUDGET_REFUSAL_CODES:
                            run.continuation["task_budget"]["native_dispatch"] = "refused_before_transport"
                    await save_runtime_run(run)
        finally:
            try:
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
                                run.execution_status = "failed"
                                run.resolution_status = "failed"
                                run.completed_at = _now()
                                run.notes = list(run.notes or [])
                                run.notes.append(f"dream provider close failed: {type(exc).__name__}")
                                await save_runtime_run(run)
                            raise
                        run = completed_run or await store.get_dream_run(run_id)
                        if run is not None:
                            run.notes = list(run.notes or [])
                            run.notes.append("dream provider close: " + json.dumps(closed, sort_keys=True))
                            await save_runtime_run(run)
            finally:
                if selected_provider is not None and hasattr(selected_provider, "_dream_owner_heartbeat"):
                    selected_provider._dream_owner_heartbeat = previous_owner_heartbeat
                if selected_provider is not None and hasattr(selected_provider, "_dream_report_persist"):
                    selected_provider._dream_report_persist = previous_report_persist


async def _report_bootstrap_writer(backend: Any, *, origin: DreamRun,
                                   prior: DreamRun | None, child_id: str) -> Any:
    """Guard the first processing checkpoint before the slice owner takes over."""
    from harness_mem.commands.dream_source_coverage import _digest
    from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError

    canonical = backend.structured_store._canonical
    origin_raw = canonical.get_payload_json("dream_runs", origin.id)
    child_raw = canonical.get_payload_json("dream_runs", child_id)
    if (origin_raw is None or _digest(json.loads(origin_raw)) != _digest(origin.to_dict())
            or (prior is None and child_raw is not None)
            or (prior is not None and (child_raw is None
                or _digest(json.loads(child_raw)) != _digest(prior.to_dict())))):
        raise CanonicalTransactionPreconditionError("terminal_report_bootstrap_changed")
    origin_sha = hashlib.sha256(origin_raw.encode()).hexdigest()
    child_sha = hashlib.sha256(child_raw.encode()).hexdigest() if child_raw is not None else None

    async def persist(value: DreamRun) -> None:
        nonlocal child_sha
        payload = value.to_dict()
        await asyncio.to_thread(canonical.apply_payload_transaction,
            idempotency_key="terminal-report-bootstrap:" + _digest({"before": child_sha, "after": payload}),
            mutations=[{"operation": "assert", "collection": "dream_runs", "entity_id": origin.id,
                        "project_name": origin.project_name, "expected_sha256": origin_sha},
                       {"operation": "upsert", "collection": "dream_runs", "entity_id": child_id,
                        "payload": payload, "expected_sha256": child_sha}])
        saved = canonical.get_payload_json("dream_runs", child_id)
        if saved is None or _digest(json.loads(saved)) != _digest(payload):
            raise CanonicalTransactionPreconditionError("terminal_report_bootstrap_readback_changed")
        child_sha = hashlib.sha256(saved.encode()).hexdigest()
        # The canonical transaction owns truth; this is the existing query
        # index projection needed to discover a newly created child.
        await asyncio.to_thread(backend.structured_store.index.upsert, "dream_runs", {
            "id": value.id, "project_name": value.project_name, "started_at": value.started_at,
            "completed_at": value.completed_at, "status": value.status,
            "trigger_source": value.trigger_source, "reflection_job_id": value.reflection_job_id,
            "policy_version": value.policy_version, "duration_ms": value.duration_ms,
        })

    return persist


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
    _maintenance_scope: Mapping[str, str] | None = None,
    _coverage_origin: DreamRun | None = None,
    _report_origin: DreamRun | None = None,
    _explicit_repair: Mapping[str, Any] | None = None,
) -> DreamRun:
    """Run one Dream maintenance pass and persist its bounded job status."""
    store = cast(LocalStructuredStore, backend.structured_store)
    started_at = _resume.started_at if _resume is not None else _now()
    notes: list[str] = list(_resume.notes or []) if _resume is not None else []
    items: list[DreamItem] = list(_resume.items) if _resume is not None else []
    if _coverage_origin is not None or _report_origin is not None:
        # This retains an original completed-source binding; it is not a new
        # source job or a replay of the failed run's ordinary manifest.
        prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
        origin = _coverage_origin or _report_origin
        notes.extend(note for note in origin.notes or [] if note.startswith(prefixes))
        notes.append(("dream retained source coverage only: " if _coverage_origin else
                      "dream retained report recheck only: ") + origin.id)
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
    report_mode = (_report_origin is not None or bool(
        run_stub.continuation.get("terminal_report_origin_run_id")))
    selected_provider = semantic_provider or _dream_provider_from_config(config, host_client=host_client)
    report_context = None
    if report_mode:
        report_origin = _report_origin or await store.get_dream_run(
            run_stub.continuation["terminal_report_origin_run_id"])
        bootstrap = await _report_bootstrap_writer(
            backend, origin=report_origin, prior=_resume, child_id=run_stub.id,
        )
        report_context = {"persist": bootstrap}
        selected_provider._dream_report_persist = bootstrap
        if _report_origin is not None:
            run_stub.continuation["terminal_report_origin_run_id"] = _report_origin.id
        await bootstrap(run_stub)
    else:
        await store.save_dream_run(run_stub)
    report_manifest = None

    async def save_run(value: DreamRun) -> None:
        if report_context is not None:
            await report_context["persist"](value)
        else:
            await store.save_dream_run(value)

    if _explicit_repair is not None:
        run_stub.continuation["explicit_repair_scope"] = copy.deepcopy(dict(_explicit_repair))
    if _explicit_repair is not None:
        recheck_signals = [DreamRecheckSignal(
            kind=group["kind"], target_ids=tuple(group["target_ids"]),
            proposed_action="merge" if group["kind"] == "duplicate" else "replace",
            risk="medium", reason="Explicitly requested source-backed memory repair.",
            cause_id="explicit_dream_repair",
        ) for group in _explicit_repair["groups"]]
    elif _report_origin is not None:
        from harness_mem.commands.dream_report_continuation import report_manifest as freeze_report_manifest
        report_manifest = await freeze_report_manifest(
            backend, _report_origin, project_name=project_name, project_root=project_root,
        )
        recheck_signals = [DreamRecheckSignal(
            kind="stale", target_ids=(row["id"],), proposed_action="replace", risk="medium",
            reason="Recheck the complete rendered attributed report under the current source contract.",
        ) for row in report_manifest["targets"]]
    elif _resume is not None:
        recheck_signals = [DreamRecheckSignal(
            kind=row["kind"], target_ids=tuple(row["target_ids"]),
            proposed_action=row["proposed_action"], risk=row["risk"],
            reason=row["reason"], cause_id=row.get("cause_id"),
        ) for row in run_stub.continuation["signals"]]
    elif _coverage_origin is not None:
        recheck_signals = []
    else:
        recheck_signals = await _detect_separated_rechecks(
            backend, project_name=project_name, project_root=project_root,
        )
    atomic_proposal_targets: set[str] = set()
    proposal_prepared_ids: set[str] = set()

    async def persist_progress(*, check_deadline: bool = True) -> None:
        checkpoint["completed_signal_indexes"] = sorted(completed_signal_indexes)
        checkpoint["unresolved_scope"] = dict(unresolved_scope)
        checkpoint["unresolved_fingerprints"] = dict(unresolved_fingerprints)
        checkpoint["verification"] = dict(saved_verification)
        run_stub.continuation = dict(checkpoint)
        run_stub.source_reviews = dict(source_reviews)
        run_stub.items = list(items)
        run_stub.notes = list(notes)
        run_stub.handling_summary = {}
        run_stub.model_post_init(None)
        if check_deadline and not atomic_proposal_targets and deadline is not None and _now() >= deadline:
            run_stub.status = "continuing"
            run_stub.completed_at = None
            run_stub.duration_ms = int(
                (_now() - started_at).total_seconds() * 1000
            )
            run_stub.notes = list(run_stub.notes or [])
            run_stub.notes.append("dream scheduling slice elapsed; source-bound progress retained for continuation")
            await save_run(run_stub)
            raise _DreamSliceYield
        await save_run(run_stub)

    recheck_cache: list[DreamRecheckRow] | None = None
    source_skip_cache: dict[str, tuple[str, str]] | None = None
    verification_cache: dict[str, Any] = {}
    verification_batches: dict[int, list[str]] = {}
    entry_snapshots: dict[str, KnowledgeEntry] = {}
    all_target_ids = list(dict.fromkeys(
        target_id for signal in recheck_signals for target_id in signal.target_ids
    ))
    checkpoint = dict(run_stub.continuation)
    if _report_origin is not None:
        from harness_mem.commands.dream_source_coverage import _digest
        checkpoint["terminal_report_origin_run_id"] = _report_origin.id
        checkpoint["terminal_report_manifest"] = report_manifest
        checkpoint["terminal_report_manifest_sha256"] = _digest(report_manifest)
        checkpoint["max_slices"] = report_manifest["max_slices"]
    if _coverage_origin is not None:
        checkpoint["terminal_source_coverage_origin_run_id"] = _coverage_origin.id
    if _maintenance_scope is not None:
        checkpoint["maintenance_scope"] = dict(_maintenance_scope)
    checkpoint.setdefault("version", "dream-slices-v3")
    checkpoint.setdefault("signals", [dict(
        kind=signal.kind, target_ids=list(signal.target_ids),
        proposed_action=signal.proposed_action, risk=signal.risk,
        reason=signal.reason, cause_id=signal.cause_id,
    ) for signal in recheck_signals])
    checkpoint.setdefault("target_ids", all_target_ids)
    if _explicit_repair is not None and "max_slices" not in checkpoint:
        repair_source = _explicit_repair.get("source") or {}
        source_units = (repair_source.get("predecessor_ids") or repair_source.get("handoff_ids")
                        or (repair_source.get("binding") or {}).get("source_candidates") or [])
        checkpoint["max_slices"] = len(all_target_ids) + 1 + 2 * len(source_units)
    if _resume is None and not report_mode and _explicit_repair is None and "max_slices" not in checkpoint:
        from harness_mem.commands.dream_source_coverage import pending_terminal_source_coverage_count
        checkpoint["terminal_source_coverage_initial_count"] = await pending_terminal_source_coverage_count(
            backend, project_name=project_name, exclude_run_id=run_stub.id,
            **({"origin_run_id": _coverage_origin.id} if _coverage_origin is not None else {}),
        )
    checkpoint.setdefault("max_slices", len(all_target_ids) + 1
                          + 2 * int(checkpoint.get("terminal_source_coverage_initial_count", 0)))
    report_bookkeeping_only = (report_mode and _resume is not None
        and set(checkpoint.get("completed_signal_indexes") or []) == set(range(len(recheck_signals))))
    checkpoint["slice_count"] = int(checkpoint.get("slice_count", 0)) + (0 if report_bookkeeping_only else 1)
    completed_signal_indexes: set[int] = set(checkpoint.get("completed_signal_indexes", []))
    unresolved_scope: dict[str, str] = dict(checkpoint.get("unresolved_scope", {}))
    unresolved_fingerprints: dict[str, Any] = dict(checkpoint.get("unresolved_fingerprints") or {})
    prior_unresolved: dict[str, Any] = {}
    if _resume is None:
        for old_run in await store.list_dream_runs(project_name, limit=8):
            if old_run is None or old_run.id == run_stub.id:
                continue
            found = old_run.continuation.get("unresolved_fingerprints") or {}
            if isinstance(found, dict) and found:
                prior_unresolved = dict(found)
                break
    feedback_rows = await backend.structured_store.query_retrieval_signals(
        project_name, signal_type="context_outcome", target_kind="knowledge_entry", limit=200,
    )
    latest_feedback: dict[str, Any] = {}
    for feedback_row in feedback_rows:
        latest_feedback.setdefault(feedback_row.target_id, feedback_row)
    if _resume is not None and checkpoint.get("verification_contract") != DREAM_SOURCE_RECHECK_CONTRACT:
        applied_targets = {item.source_id for item in items if item.final_action == "applied"}
        fingerprints = {identity: proof.get("semantic_fingerprint")
                        for identity, proof in (checkpoint.get("verification") or {}).items()
                        if isinstance(proof, dict)}
        for note in notes:
            prefix = "dream target snapshots: "
            if note.startswith(prefix):
                try:
                    for row in json.loads(note[len(prefix):]):
                        fingerprints.setdefault(row["entry_id"], row["fingerprint"])
                except (ValueError, TypeError, KeyError):
                    continue
        rejected_targets = {item.source_id for item in items
                            if item.final_action == "rejected"
                            and item.result.get("truth_change") == "none"}
        # Older contracts omitted durable-body/final-scope rejections from the
        # unresolved ledger. Recover their identities without replaying changed
        # groups, accepted writes, or any old semantic verdict.
        for identity in rejected_targets - applied_targets:
            unresolved_scope.setdefault(identity, "prior_contract_rejected_no_change")
        changed_targets: set[str] = set()
        for group in recheck_signals:
            if not set(group.target_ids).intersection(unresolved_scope):
                continue
            for identity in group.target_ids:
                entry = await store.knowledge_store.get_entry(
                    identity, project_name=project_name, project_root=project_root,
                )
                if (entry is None or fingerprints.get(identity) is None
                        or _scope_fingerprint(entry) != fingerprints[identity]):
                    changed_targets.add(identity)
        # A new source-support contract may resolve an earlier no-write result.
        # Keep its actual failed attempt in the ledger, but never reapply an
        # already changed group or replace the original complete manifest.
        completed_signal_indexes = {index for index in completed_signal_indexes
            if not (set(recheck_signals[index].target_ids).intersection(unresolved_scope)
                    and not set(recheck_signals[index].target_ids).intersection(applied_targets | changed_targets))}
    checkpoint["verification_contract"] = DREAM_SOURCE_RECHECK_CONTRACT
    saved_verification: dict[str, Any] = dict(checkpoint.get("verification", {}))
    new_verification_batches = 0
    if _explicit_repair is not None:
        await _assert_explicit_repair_targets(backend, project_name=project_name,
            project_root=project_root, scope=_explicit_repair,
            completed_indexes=completed_signal_indexes)

    def source_binding(row: Any) -> str:
        entry, validation, reopened, sources = row[:4]
        payload = {
            "verification_contract": DREAM_SOURCE_RECHECK_CONTRACT,
            "current_knowledge_project": entry.project_name,
            "semantic_fingerprint": _scope_fingerprint(entry),
            "evidence_basis": validation.evidence_basis,
            "sources": [{"kind": source.source_kind, "locator": source.locator,
                "content_sha256": source.content_sha256} for source in sources],
            "original_sources": [source.to_dict() for source in row[4]] if len(row) > 4 else None,
            "reopened": [hashlib.sha256(item.content.encode()).hexdigest() for item in reopened],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
            default=str, separators=(",", ":")).encode()).hexdigest()

    def point_proof(point: Any, text: str) -> dict[str, Any] | None:
        # A checkpoint is metadata only. Invalid/incomplete partitions cannot
        # be reused and must go through full source reopening and verification.
        if (point.report_outputs or point.replacement_items or point.output_verifications
                or point.update_meaning_judgment is not None):
            # Novel output bytes and semantic preservation verdicts are not
            # checkpoint prose. Reverify an interrupted, unapplied proposal;
            # never restore only its contradiction vote and then delete it.
            return None
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
            "proof_version": "scope-offsets-v3",
            "candidate_index": point.candidate_index,
            "semantic_support": point.semantic_support, "future_scope": point.future_scope,
            "source_use": point.source_use,
            "literal_edit_contract": point.literal_edit_contract,
            "reason_sha256": hashlib.sha256(point.reason.encode()).hexdigest(),
            "scope_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "scope_segments": segments,
            "claim_units": [{
                **unit.model_dump(mode="json", exclude={"retained_text"}),
                "retained_text_present": bool(unit.retained_text),
                "retained_text_sha256": hashlib.sha256(unit.retained_text.encode()).hexdigest(),
                "title_sha256": (hashlib.sha256(unit.retained_text[unit.title_start:unit.title_end].encode()).hexdigest()
                    if unit.title_start is not None and unit.title_end is not None else None),
                "text_sha256": hashlib.sha256("".join(
                    part.text for part in point.scope_segments[unit.first_segment:unit.end_segment_exclusive]
                ).encode()).hexdigest(),
                "original_range_sha256": hashlib.sha256("".join(
                    part.text for part in point.scope_segments[unit.first_segment:unit.end_segment_exclusive]
                ).encode()).hexdigest(),
            } for unit in point.claim_units],
        }

    def restore_point(proof: Any, text: str) -> CandidateVerificationPoint | None:
        try:
            if (not isinstance(proof, dict) or proof.get("proof_version") != "scope-offsets-v3"
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
                        != unit["text_sha256"] or unit["original_range_sha256"] != unit["text_sha256"]):
                    return None
                excluded = unit["excluded_segments"]
                if (not isinstance(excluded, list) or len(set(excluded)) != len(excluded)
                        or any(type(index) is not int or not first <= index < end for index in excluded)
                        or type(unit["retained_text_present"]) is not bool):
                    return None
                retained = ("".join(segments[index]["text"] for index in range(first, end)
                    if index not in excluded).strip() if unit["retained_text_present"] else "")
                if hashlib.sha256(retained.encode()).hexdigest() != unit["retained_text_sha256"]:
                    return None
                title_start, title_end = unit["title_start"], unit["title_end"]
                if title_start is not None or title_end is not None:
                    if (type(title_start) is not int or type(title_end) is not int
                            or not 0 <= title_start < title_end <= len(retained)
                            or hashlib.sha256(retained[title_start:title_end].encode()).hexdigest() != unit["title_sha256"]):
                        return None
                elif unit["title_sha256"] is not None:
                    return None
                units.append({"retained_text": retained, **{key: unit[key] for key in (
                    "first_segment", "end_segment_exclusive", "standalone",
                    "source_support", "source_use", "future_scope", "excluded_segments",
                    "title_start", "title_end", "title_and_text_support",
                    "selected_for_retention",
                )}})
            return CandidateVerificationPoint.model_validate({
                **{key: proof[key] for key in (
                    "candidate_index", "semantic_support", "future_scope", "source_use",
                )},
                "reason": "Reused this run's source-bound verification after current content and partition hash checks.",
                "scope_segments": segments,
                "claim_units": units,
                "literal_edit_contract": proof["literal_edit_contract"],
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
        await seal_unresolved_fingerprints()
        update_remaining()
        await persist_progress(check_deadline=False)
        run_stub.status = "continuing"
        run_stub.execution_status = "continuing"
        run_stub.resolution_status = "unresolved" if unresolved_scope else "resolved"
        run_stub.completed_at = None
        run_stub.duration_ms = int((_now() - started_at).total_seconds() * 1000)
        await save_run(run_stub)
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
        run_stub.execution_status = "failed"
        run_stub.resolution_status = "failed"
        run_stub.completed_at = _now()
        await save_run(run_stub)
        return run_stub

    if report_mode:
        # The existing provider still owns every semantic phase. Consume this
        # slice in the original task before its first native call, and keep
        # report progress under the same origin/child transaction guard.
        from harness_mem.commands.dream_report_continuation import claim_report_slice
        await persist_progress(check_deadline=False)
        report_context = await claim_report_slice(
            backend, carrier_run_id=run_stub.id, provider=selected_provider,
            config=config, host_client=host_client, project_root=project_root,
            **({"bookkeeping_only": True} if report_bookkeeping_only else {}),
        )
        selected_provider._dream_report_persist = report_context["persist"]
        selected_provider._dream_owner_heartbeat = report_context["heartbeat"]

    async def coverage_checkpoint() -> None:
        if report_mode:
            # Report refinements remain report work. They cannot create a new
            # ordinary-user extraction obligation in this finite carrier.
            await persist_progress(check_deadline=False)
            return
        # Coverage is side work of this exact run, not another target manifest
        # or source intake. Keep its outcome separate from original traversal.
        for identity, receipt in (checkpoint.get("source_coverage") or {}).items():
            if receipt.get("status") == "not_applicable":
                continue
            if receipt.get("status") == "applied":
                if str(unresolved_scope.get(identity, "")).startswith("source_coverage_"):
                    unresolved_scope.pop(identity, None)
            else:
                unresolved_scope[identity] = "source_coverage_" + str(receipt.get("status") or "pending")
        update_remaining()
        coverage = checkpoint.get("source_coverage") or {}
        applied = {item.source_id for item in items if item.final_action == "applied"
                   and item.result.get("truth_change") in {"refine", "replace"}}
        checkpoint["source_coverage_pending_ids"] = sorted(identity for identity in applied
            if (coverage.get(identity) or {}).get("status") not in {
                "applied", "no_write", "unresolved", "failed", "not_applicable"})
        await persist_progress(check_deadline=False)

    async def cover_applied_sources() -> bool:
        if report_mode or selected_provider is None or project_root is None:
            return False
        from harness_mem.commands.dream_source_coverage import run_applied_source_coverage
        return await run_applied_source_coverage(
            backend, project_name=project_name, project_root=project_root, run_id=run_stub.id,
            checkpoint=checkpoint, notes=notes, items=items, provider=selected_provider,
            persist=coverage_checkpoint, boundary=persist_progress,
        )

    # A later natural worker can carry untouched source-coverage obligations
    # from a failed task. The helper retains that task's terminal record,
    # source bindings, cumulative account and original finite slice bound.
    terminal_coverage: dict[str, Any] = {"worked": False, "pending": False}
    if (_explicit_repair is not None and _explicit_repair.get("source") is not None
            and project_root is not None):
        from harness_mem.commands.dream_source_coverage import run_explicit_source_repair
        source_repair = await run_explicit_source_repair(backend, project_name=project_name,
            project_root=project_root, run_id=run_stub.id, manifest=_explicit_repair["source"],
            checkpoint=checkpoint, notes=notes, provider=selected_provider,
            persist=lambda: persist_progress(check_deadline=False), boundary=persist_progress)
        checkpoint["explicit_source_repair_result"] = source_repair
        await persist_progress(check_deadline=False)
        if source_repair.get("pending"):
            return await continue_later()
        audit_complete = (_explicit_repair["source"].get("contract") in {
                              "explicit-dream-source-audit-v1", "explicit-source-handoff-recovery-v1"}
                          and source_repair.get("status") == "no_write")
        if source_repair.get("status") != "applied" and not audit_complete:
            unresolved_scope["explicit_source_repair"] = str(source_repair.get("status", "unresolved"))
            run_stub.status = "failed"
            run_stub.execution_status = "completed"
            run_stub.resolution_status = "unresolved"
            run_stub.completed_at = _now()
            await persist_progress(check_deadline=False)
            return run_stub
        await _assert_explicit_repair_targets(backend, project_name=project_name,
            project_root=project_root, scope=_explicit_repair,
            completed_indexes=completed_signal_indexes)
    handoff_scope = checkpoint.get("source_handoff_recovery_scope")
    if handoff_scope is not None:
        if (_explicit_repair is not None or report_mode or _coverage_origin is not None
                or _resume is None or recheck_signals
                or not isinstance(handoff_scope, dict)
                or handoff_scope.get("contract") != "explicit-source-handoff-recovery-v1"):
            raise ValueError("source_handoff_carrier_scope_invalid")
        from harness_mem.commands.source_handoff_recovery import run_source_handoff_recovery
        recovered = await run_source_handoff_recovery(backend, project_name=project_name,
            project_root=project_root, run_id=run_stub.id, manifest=handoff_scope,
            checkpoint=checkpoint, notes=notes, provider=selected_provider,
            persist=lambda: persist_progress(check_deadline=False), boundary=persist_progress)
        checkpoint["source_handoff_recovery_result"] = recovered
        await persist_progress(check_deadline=False)
        if recovered.get("pending"):
            return await continue_later()
        resolved = recovered.get("status") in {"applied", "no_write"}
        run_stub.status = "completed" if resolved else "failed"
        run_stub.execution_status = "completed"
        run_stub.resolution_status = "resolved" if resolved else "unresolved"
        run_stub.completed_at = _now()
        run_stub.duration_ms = int((run_stub.completed_at - run_stub.started_at).total_seconds() * 1000)
        await persist_progress(check_deadline=False)
        return run_stub
    if (_explicit_repair is None and not report_mode and selected_provider is not None
            and project_root is not None):
        from harness_mem.commands.dream_source_coverage import run_pending_terminal_source_coverage
        await persist_progress()
        terminal_coverage = await run_pending_terminal_source_coverage(
            backend, project_name=project_name, project_root=project_root,
            carrier_run_id=run_stub.id, provider=selected_provider,
            config=config, host_client=host_client, boundary=persist_progress,
        )
        checkpoint["terminal_source_coverage_pending"] = bool(terminal_coverage.get("pending"))
        origin = terminal_coverage.get("origin_run_id")
        if not origin and terminal_coverage.get("status") in {"blocked", "failed", "unresolved", "no_write"}:
            origin = checkpoint.get("terminal_source_coverage_origin_run_id")
            if not origin and checkpoint.get("terminal_source_coverage_initial_count", 0):
                origin = "retained-obligations"
            if origin:
                terminal_coverage = {**terminal_coverage, "origin_run_id": origin}
        if origin:
            predecessor = str(terminal_coverage.get("predecessor_id") or "task")
            key = f"{origin}:{predecessor}"
            checkpoint.setdefault("terminal_source_coverage", {})[key] = dict(terminal_coverage)
            unresolved_key = f"terminal_source_coverage:{key}"
            if terminal_coverage.get("status") in {"applied", "not_applicable"}:
                unresolved_scope.pop(unresolved_key, None)
            else:
                unresolved_scope[unresolved_key] = "source_coverage_" + str(
                    terminal_coverage.get("status") or "pending")
            await persist_progress()
    coverage_worked = bool(terminal_coverage.get("worked"))
    if not coverage_worked:
        coverage_worked = await cover_applied_sources()
    scope_coverage = await _scope_upgrade_coverage(backend, project_name, include_rejections=True)

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
        unfinished_targets = {target_id for index, group in enumerate(recheck_signals)
                              if index not in completed_signal_indexes for target_id in group.target_ids}
        for start, ids in list(verification_batches.items()):
            # An old finite batch may contain groups already completed before a
            # contract upgrade. Reopen only complete unfinished groups, without
            # dispatching their accepted or externally changed neighbors again.
            verification_batches[start] = [identity for identity in ids if identity in unfinished_targets]
            end = next((index for index in sorted(verification_batches) if index > start), len(recheck_signals))
            unfinished = next((index for index in range(start, end)
                if index not in completed_signal_indexes), None)
            if unfinished is not None and unfinished != start:
                verification_batches[unfinished] = verification_batches.pop(start)

    held_ids: set[str] = set()

    async def seal_unresolved_fingerprints() -> None:
        knowledge_store = backend.structured_store.knowledge_store
        prepared_rows = {row[0].id: row for row in (recheck_cache or [])}
        for entry_id, status in list(unresolved_scope.items()):
            existing = unresolved_fingerprints.get(entry_id)
            entry = entry_snapshots.get(entry_id) or await knowledge_store.get_entry(
                entry_id, project_name=project_name, project_root=project_root,
            )
            if entry is None:
                continue
            row = prepared_rows.get(entry_id)
            if row is not None:
                sources = row[3]
                reopen = "verified"
            else:
                sources = await knowledge_store.list_sources(entry_id)
                skip = (source_skip_cache or {}).get(entry_id)
                reopen = "missing" if skip and str(skip[1]).startswith("source_missing") else "unopened"
            fingerprint = _unresolved_fingerprint(
                entry, sources, feedback=latest_feedback.get(entry_id),
                contract=DREAM_SOURCE_RECHECK_CONTRACT, reopen=reopen,
            )
            prior = prior_unresolved.get(entry_id)
            if isinstance(prior, dict) and prior.get("fingerprint") == fingerprint and prior.get("review_after"):
                review_after = prior["review_after"]
            elif isinstance(existing, dict) and existing.get("fingerprint") == fingerprint and existing.get("review_after"):
                review_after = existing["review_after"]
            else:
                review_after = (_now() + timedelta(days=SOURCE_REVIEW_INTERVAL_DAYS)).isoformat()
            unresolved_fingerprints[entry_id] = {
                "fingerprint": fingerprint,
                "review_after": review_after,
                "contract": DREAM_SOURCE_RECHECK_CONTRACT,
                "status": status,
            }

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

                def _row_is_held(row: Any) -> bool:
                    entry = row[0]
                    prior = prior_unresolved.get(entry.id)
                    if not isinstance(prior, dict) or _review_is_due(prior, _now()):
                        return False
                    fingerprint = _unresolved_fingerprint(
                        entry, row[3], feedback=latest_feedback.get(entry.id),
                        contract=DREAM_SOURCE_RECHECK_CONTRACT, reopen="verified",
                    )
                    return (
                        prior.get("fingerprint") == fingerprint
                        and prior.get("contract") == DREAM_SOURCE_RECHECK_CONTRACT
                    )

                if (batch_rows and _resume is None and _explicit_repair is None
                        and all(_row_is_held(row) for row in batch_rows)):
                    for row in batch_rows:
                        entry = row[0]
                        prior = prior_unresolved[entry.id]
                        status = str(prior.get("status") or "unresolved")
                        unresolved_scope[entry.id] = status
                        unresolved_fingerprints[entry.id] = {
                            "fingerprint": prior.get("fingerprint"),
                            "review_after": prior.get("review_after"),
                            "contract": prior.get("contract") or DREAM_SOURCE_RECHECK_CONTRACT,
                            "status": status,
                        }
                        held_ids.add(entry.id)
                        owning = next(
                            (item for item in recheck_signals if entry.id in item.target_ids),
                            signal,
                        )
                        items.append(DreamItem(
                            source_kind=f"knowledge_{owning.kind}",
                            source_id=entry.id,
                            risk=owning.risk,
                            proposed_action=owning.proposed_action,
                            final_action="rejected",
                            reason=(
                                "Unchanged unresolved knowledge waits for a source, "
                                "feedback, contract, or due review."
                            ),
                            result={
                                "truth_change": "none",
                                "source_status": status,
                                "semantic_request": False,
                            },
                        ))
                    batch_rows = []
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
                        # One atomic native request keeps its existing executor
                        # bound. The slice yields at the persisted checkpoints
                        # before/after it instead of discarding an in-flight call.
                        receipts=notes,
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
            # Share proposal/final calls across this existing finite source
            # batch, then apply its original groups before a scheduling yield.
            # Only classification proofs are persisted, never proposal prose.
            proposal_rows = [row for row in (recheck_cache or [])
                if row[0].id in verification_batches[signal_index]
                and row[0].id in verification_cache and row[0].id not in held_ids
                and row[0].id not in proposal_prepared_ids]
            if proposal_rows:
                batch_ids = {row[0].id for row in proposal_rows}
                groups = [list(group.target_ids) for group in recheck_signals[signal_index:]
                          if set(group.target_ids).issubset(batch_ids)]
                verification_cache.update(await _verify_dream_report_confirmations(
                    backend, project_name=project_name, rechecked=proposal_rows,
                    provider=selected_provider, checked=dict(verification_cache), receipts=notes,
                ))
                verification_cache.update(await _complete_dream_proposals(
                    backend, project_name=project_name, rechecked=proposal_rows,
                    provider=selected_provider, checked=dict(verification_cache),
                    receipts=notes, comparison_groups=groups,
                    run_id=run_stub.id,
                    reassess_ids=batch_ids if _explicit_repair is not None else None,
                    consolidation_groups=[group.target_ids for group in recheck_signals[signal_index:]
                        if group.kind == "duplicate" and set(group.target_ids).issubset(batch_ids)],
                ))
                proposal_prepared_ids.update(batch_ids)
                atomic_proposal_targets.update(batch_ids)
        if set(signal.target_ids).issubset(held_ids) and signal.target_ids:
            completed_signal_indexes.add(signal_index)
            update_remaining()
            continue
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
            atomic_proposal_targets.difference_update(missing_target_ids)
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
                atomic_proposal_targets.difference_update(signal.target_ids)
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
            receipts=notes,
            proposals_prepared=all(entry.id in proposal_prepared_ids for entry in signal_entries),
        )
        items.extend(group_items)
        atomic_proposal_targets.difference_update(signal.target_ids)
        completed_signal_indexes.add(signal_index)
        for item in group_items:
            if item.final_action == "rejected":
                point = verification_cache.get(item.source_id)
                unresolved_scope.setdefault(item.source_id, "final_scope_or_proposal_rejected")
                if (point is not None and point.semantic_support == "supported"
                        and point.future_scope == "session_only"):
                    original = entry_snapshots.get(item.source_id)
                    allowed = original is not None and dream_temporary_retirement_allowed(original, point)
                    unresolved_scope[item.source_id] = (
                        "temporary_retirement_rejected" if allowed else
                        "source_scope_session_only:retirement_not_authorized"
                    )
                original = entry_snapshots.get(item.source_id)
                if original is not None:
                    scope_coverage[item.source_id] = {
                        "fingerprint": _scope_fingerprint(original),
                        "scope_status": unresolved_scope[item.source_id],
                        "semantic_support": point.semantic_support if point is not None else "unclear",
                    }
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
            if item.final_action == "applied" and item.result.get("truth_change") in {
                    "refine", "replace", "covered_by_replacement", "deleted"}:
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
            if item.final_action != "applied" or item.result.get("truth_change") not in {"refine", "replace"}:
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
        if (str(signal.cause_id or "").startswith("source-anchor:")
                and {item.source_id for item in group_items} == set(signal.target_ids)
                and all(item.final_action == "applied"
                    and item.result.get("truth_change") == "verification_refreshed" for item in group_items)
                and not set(signal.target_ids).intersection(unresolved_scope)):
            for identity in signal.target_ids:
                if identity in scope_coverage:
                    scope_coverage[identity]["compared_groups"] = sorted(set([
                        *(scope_coverage[identity].get("compared_groups") or []), str(signal.cause_id)]))
        record_scope_coverage()
        update_remaining()
        await persist_progress()

    if not coverage_worked:
        await cover_applied_sources()
    await coverage_checkpoint()
    if checkpoint.get("source_coverage_pending_ids") or terminal_coverage.get("pending"):
        return await continue_later()
    await seal_unresolved_fingerprints()
    checkpoint["unresolved_fingerprints"] = dict(unresolved_fingerprints)
    completed_at = _now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    item_failed = any(item.final_action == "failed" for item in items)
    final_status: Literal["completed", "failed"] = (
        "failed" if unresolved_scope or item_failed else "completed"
    )
    execution_status: Literal["completed", "failed", "continuing"] = (
        "failed" if item_failed else "completed"
    )
    resolution_status: Literal["resolved", "unresolved", "failed"] = (
        "failed" if item_failed else "unresolved" if unresolved_scope else "resolved"
    )
    run = DreamRun(
        id=run_stub.id,
        project_name=project_name,
        started_at=started_at,
        completed_at=completed_at,
        status=final_status,
        execution_status=execution_status,
        resolution_status=resolution_status,
        trigger_source=source,
        reflection_job_id=reflection_job_id,
        items=items,
        duration_ms=duration_ms,
        notes=notes if notes else None,
        continuation={**checkpoint, "completed_signal_indexes": sorted(completed_signal_indexes),
            "execution_status": execution_status, "resolution_status": resolution_status,
            # Retain finite metadata proofs for deletion/refinement audit after
            # source locator rows are normally removed; never retain bodies.
            "unresolved_scope": dict(unresolved_scope),
            "unresolved_fingerprints": dict(unresolved_fingerprints),
            "verification": dict(saved_verification)},
        source_reviews=dict(source_reviews),
    )
    await save_run(run)
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
    coverage_origin_run_id: str | None = None,
    report_origin_run_id: str | None = None,
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
                **({"coverage_origin_run_id": coverage_origin_run_id} if coverage_origin_run_id else {}),
                **({"report_origin_run_id": report_origin_run_id} if report_origin_run_id else {}),
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
    coverage_origin_run_id: str | None = None,
    report_origin_run_id: str | None = None,
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
    coverage_scope = None
    coverage_source_job_id = None
    coverage_origin_ref = coverage_origin_run_id
    if report_origin_run_id:
        from harness_mem.commands.dream_report_continuation import bound_terminal_report_origin
        from harness_mem.hook_background import background_generation_from_env
        if (resume_run_id or coverage_origin_run_id or source != "ide_hook" or not host_client
                or os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1"):
            raise ValueError("terminal_report_detached_owner_required")
        _origin, generation, original_trigger, coverage_source_job_id = await bound_terminal_report_origin(
            backend, project_name=project_name, project_root=project_root, config=config,
            host_client=host_client, origin_run_id=report_origin_run_id,
        )
        if background_generation_from_env() != generation or trigger_id != original_trigger:
            raise ValueError("terminal_report_account_mismatch")
        coverage_scope = {"trigger_id": original_trigger, "dispatch_generation": generation}
        coverage_origin_ref = report_origin_run_id
        trigger_job_id = None
    if coverage_origin_run_id:
        from harness_mem.commands.dream_source_coverage import bound_terminal_source_coverage_origin
        from harness_mem.hook_background import background_generation_from_env
        if (resume_run_id or source != "ide_hook" or not host_client
                or os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1"):
            raise ValueError("terminal_source_coverage_detached_owner_required")
        _origin, generation, original_trigger, coverage_source_job_id = await bound_terminal_source_coverage_origin(
            backend, project_name=project_name, project_root=project_root, config=config,
            host_client=host_client, origin_run_id=coverage_origin_run_id,
        )
        if background_generation_from_env() != generation or trigger_id != original_trigger:
            raise ValueError("terminal_source_coverage_account_mismatch")
        coverage_scope = {"trigger_id": original_trigger, "dispatch_generation": generation}
        trigger_job_id = None
    if resume_run_id:
        requested_run = await cast(LocalStructuredStore, backend.structured_store).get_dream_run(resume_run_id)
        if (requested_run is None or requested_run.project_name != project_name
                or requested_run.status != "continuing"
                or requested_run.continuation.get("version") != "dream-slices-v3"):
            return {"success": False, "status": "failed", "project_name": project_name,
                "run_id": resume_run_id, "reason": "requested Dream continuation is not resumable"}
        # A continuation is the same maintenance request, never another source job.
        trigger_job_id = None
        # Each slice owns a fresh reflection claim. Retain the completed-source
        # and pinned-origin references required by its coverage owner.
        prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
        original_jobs = {note[len(prefix):].strip() for note in requested_run.notes or []
                         for prefix in prefixes if note.startswith(prefix)}
        if len(original_jobs) == 1:
            coverage_source_job_id = next(iter(original_jobs))
        coverage_origin_ref = (requested_run.continuation.get("terminal_source_coverage_origin_run_id")
                               or requested_run.continuation.get("terminal_report_origin_run_id"))
    hook_session: dict[str, Any] | None = None
    legacy_accounting_failure: dict[str, str] | None = None
    if source == "ide_hook" and trigger_job_id:
        from harness_mem.autonomous.worker import excluded_trigger_result
        from harness_mem.commands.support import detect_runtime_client, normalize_client_name
        from harness_mem.hook_background import background_generation_from_env

        trigger_job = backend.transcript_store.get_distill_job(trigger_job_id)
        resolved_host_client = (
            normalize_client_name(host_client)
            if host_client
            else normalize_client_name(getattr(trigger_job, "client", None))
            if trigger_job is not None
            else detect_runtime_client()
        )
        if trigger_job is not None:
            excluded = excluded_trigger_result(
                backend, trigger_job, project_name=project_name, project_root=project_root, config=config,
                trigger_id=trigger_id, client=resolved_host_client or "unknown", launch_source=source,
                dispatch_generation=background_generation_from_env(),
            )
            if excluded is not None:
                return await _record_dream_tick(
                    backend, project_name=project_name, source=source, trigger_id=trigger_id,
                    payload={"success": excluded["success"], "status": "skipped" if excluded["success"] else "failed",
                             "project_name": project_name, "reason": excluded["reason"],
                             "session_distill": _dream_session_receipt(excluded, excluded["receipt"]["job_id"])},
                )
        auth_status = background_status(config, client=resolved_host_client)
        execution_client = resolved_host_client or auth_status.selected_cli or "unknown"
        if not auth_status.ready:
            from harness_mem.autonomous.worker import (
                record_post_turn_preflight_failure,
            )

            if auth_status.reason == "disabled":
                message = "Hook-started Dream needs distill.autonomous.enabled=true."
            elif auth_status.reason == "unsupported_cli":
                message = (
                    f"No background CLI is implemented for '{auth_status.selected_cli}'."
                )
            elif auth_status.reason == "host_not_detected":
                message = "The current Agent host could not be identified."
            elif auth_status.reason == "cli_not_found":
                message = (
                    f"The selected background CLI '{auth_status.selected_cli}' was not found."
                )
            else:
                message = background_reason_message(auth_status.reason)
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

        # Preserve the old paid source account before a new source completion
        # replaces last_verified_completion in the existing per-project receipt.
        latest_runs = await cast(LocalStructuredStore, backend.structured_store).list_dream_runs(
            project_name, limit=1,
        )
        pending_legacy = latest_runs[0] if latest_runs else None
        if (pending_legacy is not None and pending_legacy.status == "continuing"
                and pending_legacy.continuation.get("version") == "dream-slices-v3"
                and not pending_legacy.continuation.get("maintenance_scope")):
            from harness_mem.autonomous.executors.task_budget import (
                bind_maintenance_task, is_production_native_host, seed_legacy_task_budget, TaskBudgetRefusal,
            )
            selected_host = auth_status.selected_cli or execution_client
            if is_production_native_host(selected_host):
                try:
                    old_scope, old_calls = _legacy_dream_accounting(
                        backend, pending_legacy, project_root=project_root, host_client=selected_host,
                    )
                    old_binding = bind_maintenance_task(
                        data_dir=Path(backend.data_dir), host_client=selected_host,
                        config=config, **old_scope,
                    )
                    seed_legacy_task_budget(old_binding, calls=old_calls, legacy_run_id=pending_legacy.id)
                    pending_legacy.continuation["maintenance_scope"] = old_scope
                    await backend.structured_store.save_dream_run(pending_legacy)
                except TaskBudgetRefusal as exc:
                    legacy_accounting_failure = {"code": exc.code, "run_id": pending_legacy.id}
                    pending_legacy.continuation["legacy_accounting_failure"] = legacy_accounting_failure
                    await backend.structured_store.save_dream_run(pending_legacy)

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
        if hook_session.get("reason") == "manual_session_owned":
            return await _record_dream_tick(
                backend, project_name=project_name, source=source, trigger_id=trigger_id,
                payload={"success": True, "status": "skipped", "project_name": project_name,
                         "reason": "manual_session_owned",
                         "session_distill": _dream_session_receipt(hook_session, trigger_job_id)},
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

    if legacy_accounting_failure is not None:
        return await _record_dream_tick(
            backend, project_name=project_name, source=source, trigger_id=trigger_id,
            payload={"success": False, "status": "failed", "project_name": project_name,
                     "run_id": legacy_accounting_failure["run_id"],
                     "reason": "legacy Dream accounting unavailable; independent source processing retained",
                     "failure_reason": legacy_accounting_failure["code"],
                     "session_distill": _dream_session_receipt(hook_session or {}, trigger_job_id)},
        )

    decision = await dream_scheduler_decision(
        backend,
        project_name=project_name,
        config=config,
    )
    force_for_hook_session = (hook_session is not None or resume_run_id is not None
                              or coverage_origin_run_id is not None or report_origin_run_id is not None)
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
        input_refs=list(dict.fromkeys(
            value
            for value in (decision.last_run_id, trigger_job_id, coverage_origin_ref, coverage_source_job_id)
            if value
        )),
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
        from harness_mem.hook_background import background_generation_from_env

        maintenance_scope = coverage_scope or {"trigger_id": trigger_id or f"dream-job-{job.id}",
            "dispatch_generation": background_generation_from_env() or f"dream-job-{job.id}"}
        # A completed source job may be replaying only a failed Note on a later
        # Stop. Keep the paid source invocation's scope, not the replay caller's
        # fresh generation. Dream continuations additionally bind their own
        # persisted scope in dream_once.
        completed_source = ((hook_session or {}).get("receipt") or {}).get("last_verified_completion")
        if (isinstance(completed_source, dict)
                and completed_source.get("job_id") == trigger_job_id
                and completed_source.get("session_id") == trigger_id
                and completed_source.get("trigger_id") == trigger_id
                and completed_source.get("dispatch_generation")):
            maintenance_scope = {"trigger_id": str(completed_source["trigger_id"]),
                "dispatch_generation": str(completed_source["dispatch_generation"])}
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
            maintenance_scope=maintenance_scope,
            **({"coverage_origin_run_id": coverage_origin_run_id} if coverage_origin_run_id else {}),
            **({"report_origin_run_id": report_origin_run_id} if report_origin_run_id else {}),
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
        failure_run: dict[str, Any] = {}
        if isinstance(exc, ProviderError) and getattr(exc, "_source_coverage_provider_failure", False):
            failed_id = getattr(exc, "_source_coverage_run_id", None)
            failed = await cast(LocalStructuredStore, backend.structured_store).get_dream_run(failed_id) if failed_id else None
            if failed is not None and failed.project_name == project_name and failed.reflection_job_id == job.id:
                failure_run = {"run_id": failed.id, "execution_status": failed.execution_status,
                    "resolution_status": failed.resolution_status,
                    "source_coverage_failure": failed.continuation.get("source_coverage_failure")}
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
                **failure_run,
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
    maintenance_scope: Mapping[str, str] | None = None,
    coverage_origin_run_id: str | None = None,
    report_origin_run_id: str | None = None,
) -> DreamRun:
    seconds = max(1, timeout_seconds)
    deadline = _now() + timedelta(seconds=seconds)
    # One bounded group may classify, propose, verify outputs, revise once,
    # verify the revision and confirm reports. Task budgets remain unchanged.
    # Each request keeps its existing executor deadline before checkpoint/yield.
    # This watchdog remains finite; cancellation reaping (45s) and provider
    # close (20s) retain their separate bounded cleanup waits.
    watchdog_seconds = seconds + 6 * _verification_runtime_seconds(semantic_provider)
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
                maintenance_scope=maintenance_scope,
                **({"coverage_origin_run_id": coverage_origin_run_id} if coverage_origin_run_id else {}),
                **({"report_origin_run_id": report_origin_run_id} if report_origin_run_id else {}),
            ),
            timeout=watchdog_seconds,
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
            run.execution_status = "failed"
            run.resolution_status = "failed"
            run.completed_at = completed_at
            run.duration_ms = int(
                (completed_at - run.started_at).total_seconds() * 1000
            )
            run.notes = list(run.notes or [])
            run.notes.append("dream slice watchdog exceeded scheduling plus native decision runtime")
            await store.save_dream_run(run)
        raise TimeoutError("dream slice watchdog exceeded scheduling plus native decision runtime") from None


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
