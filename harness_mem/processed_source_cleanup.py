"""Post-distill source cleanup that preserves promoted project truth.

This is deliberately separate from privacy ``hard_delete``.  Privacy erasure
removes the complete reference closure, including durable truth; processed
source cleanup removes only raw/session evidence and redacts provenance on
truth that already passed governance.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RelationFact,
    RuleCandidate,
    Skill,
)
from harness_mem.governance_status import (
    HISTORICAL_LAYER_STATUSES,
    TRUTH_LAYER_STATUSES,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.canonical_store import count_managed_backup_observations

_TRUTH_COLLECTIONS = {
    "memory_entries",
    "rule_candidates",
    "relation_facts",
    "confirmed_rules",
    "skills",
}
_GOVERNED_CANDIDATE_COLLECTIONS = {
    "memory_entries",
    "rule_candidates",
    "relation_facts",
}
_AUXILIARY_COLLECTIONS = (
    "procedural_candidates",
    "supersede_candidates",
    "merge_suggestion_candidates",
    "stale_truth_suggestion_candidates",
    "task_handoffs",
    "retrieval_signals",
    "metabolism_runs",
    "dream_runs",
)
_SAFE_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


async def retry_retained_source_cleanups(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    authorized: bool,
    limit: int = 4,
    minimum_age_seconds: int = 300,
) -> dict[str, Any]:
    """Retry a bounded, cooled-down set through existing maintenance hooks."""

    if not authorized:
        return {
            "attempted": 0,
            "deleted": 0,
            "retained": 0,
            "partial_failure": 0,
            "unsupported": 0,
            "outcomes": [],
            "reason": "source_cleanup_not_authorized",
        }

    from harness_mem.native_source_cleanup import (
        apply_native_source_cleanup,
        plan_native_source_cleanup,
    )

    list_jobs = getattr(backend.transcript_store, "list_distill_jobs", None)
    if not callable(list_jobs):
        return {
            "attempted": 0,
            "deleted": 0,
            "retained": 0,
            "partial_failure": 0,
            "unsupported": 0,
            "outcomes": [],
            "reason": "source_cleanup_store_unavailable",
        }

    retry_before = datetime.now(timezone.utc) - timedelta(
        seconds=max(0, int(minimum_age_seconds))
    )
    jobs = [
        job
        for job in list_jobs(
            project_name=project_name,
            status="completed",
            limit=100_000,
        )
        if job.completion_disposition is not None
        and job.source_cleanup_status in {"retained", "partial_failure"}
        and job.updated_at <= retry_before
    ]
    jobs.sort(key=lambda item: item.completed_at or item.updated_at)
    outcomes: list[dict[str, Any]] = []
    for job in jobs[: max(0, int(limit))]:
        source = backend.transcript_store.get_source(job.source_id)
        if source is None or source.source_revision != job.source_revision:
            outcomes.append(
                {
                    "job_id_sha256": _digest(job.id),
                    "status": "retained",
                    "reason_codes": ["source_revision_changed"],
                }
            )
            continue
        native_plan = plan_native_source_cleanup(source)
        preview = native_plan.to_preview()
        if native_plan.retained:
            outcomes.append(
                {
                    "job_id_sha256": _digest(job.id),
                    "status": "retained",
                    "reason_codes": list(preview.get("reason_codes") or []),
                }
            )
            continue
        receipt_id: str | None = None
        if native_plan.supported:
            begun = begin_processed_source_cleanup(
                backend,
                job_id=job.id,
                native_preview=preview,
            )
            if not begun.get("success"):
                outcomes.append(
                    {
                        "job_id_sha256": _digest(job.id),
                        "status": "partial_failure",
                        "reason_codes": list(begun.get("reason_codes") or []),
                    }
                )
                continue
            receipt_id = str(begun["receipt_id"])
        native_result = apply_native_source_cleanup(native_plan)
        result = await cleanup_processed_source(
            backend,
            job_id=job.id,
            native_cleanup=native_result,
            receipt_id=receipt_id,
        )
        outcomes.append(
            {
                "job_id_sha256": _digest(job.id),
                "status": result.get("status"),
                "reason_codes": list(result.get("reason_codes") or []),
            }
        )
    return {
        "attempted": len(outcomes),
        "deleted": sum(item["status"] == "deleted" for item in outcomes),
        "retained": sum(item["status"] == "retained" for item in outcomes),
        "partial_failure": sum(
            item["status"] == "partial_failure" for item in outcomes
        ),
        "unsupported": sum(item["status"] == "unsupported" for item in outcomes),
        "outcomes": outcomes,
    }


async def cleanup_processed_source(
    backend: LocalMemoryBackend,
    *,
    job_id: str,
    native_cleanup: dict[str, Any],
    receipt_id: str | None = None,
) -> dict[str, Any]:
    """Clean raw evidence for one completed job and retain sanitized truth.

    ``native_cleanup`` is the result of the host-specific remover.  Paths,
    session ids, exception messages, and source content from that result are
    intentionally never copied into the durable receipt.
    """

    job = backend.transcript_store.get_distill_job(job_id)
    if job is None:
        return _result(
            success=False,
            status="partial_failure",
            receipt_id=None,
            counts={},
            reason_codes=["distill_job_not_found"],
        )
    if job.status != "completed":
        return _result(
            success=False,
            status="partial_failure",
            receipt_id=None,
            counts={},
            reason_codes=["distill_job_not_completed"],
        )

    existing_receipt = (
        _find_deletion_receipt(backend, job.project_name, receipt_id)
        if receipt_id is not None
        else None
    )
    if receipt_id is not None and existing_receipt is None:
        return _result(
            success=False,
            status="partial_failure",
            receipt_id=receipt_id,
            counts={},
            reason_codes=["in_progress_receipt_not_found"],
        )
    receipt_id = receipt_id or str(uuid4())
    reason_codes = _native_reason_codes(native_cleanup)
    native_status = _native_status(native_cleanup)
    if existing_receipt is not None:
        if (
            existing_receipt.get("kind") != "processed_source_cleanup"
            or existing_receipt.get("status") != "in_progress"
        ):
            return _result(
                success=False,
                status="partial_failure",
                receipt_id=receipt_id,
                counts={},
                reason_codes=["in_progress_receipt_invalid"],
            )
        receipt = dict(existing_receipt)
        receipt["reason_codes"] = list(
            dict.fromkeys(
                [
                    *_safe_reason_codes(existing_receipt.get("reason_codes") or []),
                    *reason_codes,
                ]
            )
        )
        native_receipt = dict(existing_receipt.get("native_cleanup") or {})
        native_receipt["status"] = native_status
        receipt["native_cleanup"] = native_receipt
        reason_codes = list(receipt["reason_codes"])
    else:
        receipt = _new_receipt(
            receipt_id=receipt_id,
            job=job,
            native_status=native_status,
            reason_codes=reason_codes,
        )
    _add_revision_scope(backend, job, receipt)
    try:
        backend.transcript_store.save_deletion_receipt(receipt)
    except Exception:
        return _result(
            success=False,
            status="partial_failure",
            receipt_id=None,
            counts={},
            reason_codes=["receipt_persistence_failed"],
        )
    try:
        backup_matches = count_managed_backup_observations(
            backend.data_dir,
            project_name=job.project_name,
            transcript_source_id=job.source_id,
        )
    except Exception:
        backup_matches = -1
    if backup_matches:
        reason = (
            "managed_backup_probe_failed"
            if backup_matches < 0
            else "managed_backup_contains_source_evidence"
        )
        return _finish_failure(
            backend,
            job=job,
            receipt=receipt,
            receipt_id=receipt_id,
            reason_codes=[*reason_codes, reason],
            operation="managed_backup_gate",
            counts={"managed_backup_observations": max(0, backup_matches)},
        )
    if native_status != "deleted":
        status = "unsupported" if native_status == "unsupported" else "partial_failure"
        reason_codes = list(dict.fromkeys([
            *reason_codes,
            "native_cleanup_unsupported"
            if status == "unsupported"
            else "native_cleanup_incomplete",
        ]))
        _record_job_cleanup_outcome(
            backend,
            job,
            status=status,
            receipt_id=receipt_id,
            reason_codes=reason_codes,
        )
        receipt.update(
            {
                "status": status,
                "completed_at": _utc_now(),
                "reason_codes": reason_codes,
                "actual_removal": {},
                "verification": {"passed": False, "remaining": {}},
            }
        )
        backend.transcript_store.save_deletion_receipt(receipt)
        return _result(
            success=False,
            status=status,
            receipt_id=receipt_id,
            counts={},
            reason_codes=reason_codes,
        )

    try:
        plan = _plan_structured_cleanup(backend, job)
    except Exception as exc:
        return _finish_failure(
            backend,
            job=job,
            receipt=receipt,
            receipt_id=receipt_id,
            reason_codes=[*reason_codes, _failure_code(exc)],
            operation="plan",
            counts={},
        )

    receipt["plan_counts"] = {
        "observations": len(plan["observation_ids"]),
        "truth_to_sanitize": sum(len(ids) for ids in plan["retain"].values()),
        "derived_records": sum(len(ids) for ids in plan["delete"].values()),
        "blocking_candidates": len(plan["blocking_candidate_ids"]),
    }
    try:
        backend.transcript_store.save_deletion_receipt(receipt)
    except Exception:
        return _finish_failure(
            backend,
            job=job,
            receipt=receipt,
            receipt_id=receipt_id,
            reason_codes=[*reason_codes, "receipt_plan_update_failed"],
            operation="receipt_plan",
            counts={},
        )

    if plan["blocking_candidate_ids"]:
        return _finish_failure(
            backend,
            job=job,
            receipt=receipt,
            receipt_id=receipt_id,
            reason_codes=[*reason_codes, "unresolved_candidates"],
            operation="governance_gate",
            counts={"blocking_candidates": len(plan["blocking_candidate_ids"])},
        )

    counts: dict[str, int] = {
        "truth_sanitized": 0,
        "derived_records_deleted": 0,
        "observations_deleted": 0,
    }
    operation = "structured_truth"
    try:
        counts["truth_sanitized"] = await _sanitize_truth(
            backend,
            plan,
            receipt_id=receipt_id,
        )
        operation = "derived_records"
        structured_store = _structured_store(backend)
        for collection, entity_ids in plan["delete"].items():
            for entity_id in entity_ids:
                counts["derived_records_deleted"] += int(
                    structured_store.hard_delete_record(collection, entity_id)
                )

        operation = "observations"
        for observation_id in plan["observation_ids"]:
            current_observation = await backend.verbatim_store.get(observation_id)
            if current_observation is not None and str(
                current_observation.metadata.get("source_revision") or ""
            ) != job.source_revision:
                raise RuntimeError("observation_revision_changed")
            counts["observations_deleted"] += int(
                await backend.verbatim_store.delete(observation_id)
            )

        operation = "transcript_ledger"
        ledger_counts = backend.transcript_store.prune_completed_distill_evidence(
            job_id,
            receipt_id=receipt_id,
        )
        counts.update(ledger_counts)

        operation = "secure_delete_flush"
        _verbatim_store(backend).flush_sensitive_deletes()
        _structured_store(backend).flush_sensitive_deletes()
        backend.transcript_store.flush_sensitive_deletes()
        counts["secure_delete_flushes"] = 3

        operation = "verification"
        remaining = await _verify_cleanup(
            backend,
            job_id=job_id,
            observation_ids=plan["observation_ids"],
            retained_truth=plan["retain"],
            deleted_records=plan["delete"],
        )
        passed = not any(remaining.values())
        status = "deleted" if passed else "partial_failure"
        final_job = backend.transcript_store.get_distill_job(job_id) or job
        final_reasons = list(
            dict.fromkeys(
                [
                    *reason_codes,
                    (
                        "processed_source_deleted"
                        if passed
                        else "cleanup_verification_failed"
                    ),
                ]
            )
        )
        _record_job_cleanup_outcome(
            backend,
            final_job,
            status=status,
            receipt_id=receipt_id,
            reason_codes=final_reasons,
        )
        receipt.update(
            {
                "status": "succeeded" if passed else "partial_failure",
                "completed_at": _utc_now(),
                "reason_codes": final_reasons,
                "actual_removal": dict(counts),
                "verification": {"passed": passed, "remaining": remaining},
            }
        )
        backend.transcript_store.save_deletion_receipt(receipt)
        return _result(
            success=passed,
            status=status,
            receipt_id=receipt_id,
            counts=counts,
            reason_codes=final_reasons,
        )
    except Exception as exc:
        return _finish_failure(
            backend,
            job=backend.transcript_store.get_distill_job(job_id) or job,
            receipt=receipt,
            receipt_id=receipt_id,
            reason_codes=[*reason_codes, _failure_code(exc)],
            operation=operation,
            counts=counts,
        )


def _plan_structured_cleanup(
    backend: LocalMemoryBackend,
    job: Any,
) -> dict[str, Any]:
    verbatim = _verbatim_store(backend)
    structured = _structured_store(backend)
    observation_ids = {
        str(payload.get("id") or "")
        for payload in verbatim.list_record_payloads_for_lifecycle()
        if _observation_matches(payload, job)
    }
    retain: dict[str, set[str]] = {collection: set() for collection in _TRUTH_COLLECTIONS}
    delete: dict[str, set[str]] = {}
    blocking: set[str] = set()
    candidate_ids: set[str] = set(map(str, job.output_candidate_ids))
    removed_ids = {str(job.id), *observation_ids}
    allow_legacy_session_fallback = _legacy_session_fallback_allowed(backend, job)

    for collection in _GOVERNED_CANDIDATE_COLLECTIONS:
        for payload in structured.list_record_payloads(collection, strict=True):
            entity_id = str(payload.get("id") or "")
            if not entity_id or str(payload.get("project_name") or "") != job.project_name:
                continue
            if entity_id in candidate_ids or _payload_matches_job(
                payload,
                job,
                observation_ids,
                allow_legacy_session_fallback=allow_legacy_session_fallback,
            ):
                candidate_ids.add(entity_id)
                status = str(payload.get("status") or "pending")
                if status in {"pending", "deferred"}:
                    blocking.add(entity_id)
                elif status in TRUTH_LAYER_STATUSES or status in HISTORICAL_LAYER_STATUSES:
                    retain[collection].add(entity_id)
                elif status == "rejected":
                    delete.setdefault(collection, set()).add(entity_id)
                    removed_ids.add(entity_id)
                else:
                    blocking.add(entity_id)

    for collection in ("confirmed_rules", "skills"):
        for payload in structured.list_record_payloads(collection, strict=True):
            entity_id = str(payload.get("id") or "")
            if not entity_id or str(payload.get("project_name") or "") != job.project_name:
                continue
            if (
                str(payload.get("source_candidate_id") or "") in candidate_ids
                or _payload_matches_job(
                    payload,
                    job,
                    observation_ids,
                    allow_legacy_session_fallback=allow_legacy_session_fallback,
                )
            ):
                retain[collection].add(entity_id)

    # Remove evidence-only rows that directly reference raw/job ids or a
    # rejected derived record. Retained truth ids are intentionally not seeds:
    # later usage signals for surviving truth must not be erased transitively.
    changed = True
    while changed:
        changed = False
        for collection in _AUXILIARY_COLLECTIONS:
            for payload in structured.list_record_payloads(collection, strict=True):
                entity_id = str(payload.get("id") or "")
                if (
                    not entity_id
                    or entity_id in delete.get(collection, set())
                    or str(payload.get("project_name") or "") != job.project_name
                ):
                    continue
                if _payload_matches_job(
                    payload,
                    job,
                    observation_ids,
                    allow_legacy_session_fallback=allow_legacy_session_fallback,
                ) or bool(
                    _reference_ids(payload).intersection(removed_ids)
                ):
                    delete.setdefault(collection, set()).add(entity_id)
                    removed_ids.add(entity_id)
                    changed = True

    return {
        "observation_ids": sorted(observation_ids),
        "retain": {
            collection: sorted(entity_ids)
            for collection, entity_ids in retain.items()
            if entity_ids
        },
        "delete": {
            collection: sorted(entity_ids)
            for collection, entity_ids in delete.items()
            if entity_ids
        },
        "blocking_candidate_ids": sorted(blocking),
    }


async def _sanitize_truth(
    backend: LocalMemoryBackend,
    plan: dict[str, Any],
    *,
    receipt_id: str,
) -> int:
    from harness_mem.commands.evidence_admission import sanitize_evidence_refs

    store = _structured_store(backend)
    total = 0
    for collection, entity_ids in plan["retain"].items():
        for entity_id in entity_ids:
            payload = store.read_record_payload(collection, entity_id)
            if collection == "memory_entries":
                memory = MemoryEntry.from_dict(payload)
                memory.source = "processed_source_pruned"
                memory.distill_job_id = None
                memory.provenance = _pruned_provenance(receipt_id)
                sanitize_evidence_refs(memory)
                await store.save_memory_entry(memory)
            elif collection == "rule_candidates":
                rule_candidate = RuleCandidate.from_dict(payload)
                rule_candidate.session_id = ""
                rule_candidate.distill_job_id = None
                sanitize_evidence_refs(rule_candidate)
                await store.save_rule_candidate(rule_candidate)
            elif collection == "relation_facts":
                relation = RelationFact.from_dict(payload)
                relation.evidence = "Source evidence pruned after completed distill."
                relation.source = "processed_source_pruned"
                relation.distill_job_id = None
                relation.provenance = _pruned_provenance(receipt_id)
                sanitize_evidence_refs(relation)
                await store.save_relation_fact(relation)
            elif collection == "confirmed_rules":
                confirmed_rule = ConfirmedRule.from_dict(payload)
                confirmed_rule.source_session_id = ""
                confirmed_rule.provenance = _pruned_provenance(receipt_id)
                store.write_record_payload(
                    "confirmed_rules",
                    confirmed_rule.id,
                    confirmed_rule.to_dict(),
                )
                store.index.update(
                    "confirmed_rules",
                    confirmed_rule.id,
                    {"source_session_id": ""},
                )
            elif collection == "skills":
                skill = Skill.from_dict(payload)
                skill.source_session_id = ""
                skill.source_ids = [
                    value for value in skill.source_ids
                    if value and value != payload.get("source_session_id")
                ]
                store.write_record_payload("skills", skill.id, skill.to_dict())
                store.index.update(
                    "skills",
                    skill.id,
                    {
                        "source_session_id": "",
                        "source_ids": skill.source_ids,
                    },
                )
            total += 1
    return total


async def _verify_cleanup(
    backend: LocalMemoryBackend,
    *,
    job_id: str,
    observation_ids: list[str],
    retained_truth: dict[str, list[str]],
    deleted_records: dict[str, list[str]],
) -> dict[str, int]:
    remaining = backend.transcript_store.verify_completed_distill_evidence_pruned(job_id)
    # A retained completed job is required, not a residual error.
    remaining["completed_job"] = int(remaining.get("completed_job") != 1)
    remaining["observations"] = 0
    for observation_id in observation_ids:
        remaining["observations"] += int(
            await backend.verbatim_store.get(observation_id) is not None
        )
    store = _structured_store(backend)
    remaining["deleted_records"] = sum(
        int(store.record_payload_exists(collection, entity_id))
        for collection, entity_ids in deleted_records.items()
        for entity_id in entity_ids
    )
    remaining["truth_missing"] = sum(
        int(not store.record_payload_exists(collection, entity_id))
        for collection, entity_ids in retained_truth.items()
        for entity_id in entity_ids
    )
    remaining["truth_provenance"] = sum(
        int(_payload_has_raw_provenance(store.read_record_payload(collection, entity_id)))
        for collection, entity_ids in retained_truth.items()
        for entity_id in entity_ids
        if store.record_payload_exists(collection, entity_id)
    )
    completed_job = backend.transcript_store.get_distill_job(job_id)
    if completed_job is None:
        remaining["managed_backup_observations"] = 1
    else:
        try:
            remaining["managed_backup_observations"] = (
                count_managed_backup_observations(
                    backend.data_dir,
                    project_name=completed_job.project_name,
                    transcript_source_id=completed_job.source_id,
                )
            )
        except Exception:
            remaining["managed_backup_observations"] = 1
    return remaining


def _record_job_cleanup_outcome(
    backend: LocalMemoryBackend,
    job: Any,
    *,
    status: str,
    receipt_id: str,
    reason_codes: list[str],
) -> None:
    disposition = job.completion_disposition
    backend.transcript_store.record_distill_completion_outcome(
        job.id,
        disposition=disposition,
        reason_codes=list(dict.fromkeys([*job.completion_reason_codes, *reason_codes])),
        promotion_summary=dict(job.promotion_summary),
        source_cleanup_status=status,
        source_cleanup_receipt_id=receipt_id,
    )


def _finish_failure(
    backend: LocalMemoryBackend,
    *,
    job: Any,
    receipt: dict[str, Any],
    receipt_id: str,
    reason_codes: list[str],
    operation: str,
    counts: dict[str, int],
) -> dict[str, Any]:
    safe_reasons = list(dict.fromkeys(_safe_reason_codes(reason_codes)))
    try:
        _record_job_cleanup_outcome(
            backend,
            job,
            status="partial_failure",
            receipt_id=receipt_id,
            reason_codes=safe_reasons,
        )
    except Exception:
        safe_reasons = list(dict.fromkeys([*safe_reasons, "job_receipt_update_failed"]))
    receipt.update(
        {
            "status": "partial_failure",
            "completed_at": _utc_now(),
            "reason_codes": safe_reasons,
            "actual_removal": dict(counts),
            "verification": {"passed": False, "remaining": {}},
            "failure": {"operation": operation},
        }
    )
    try:
        backend.transcript_store.save_deletion_receipt(receipt)
    except Exception:
        safe_reasons = list(dict.fromkeys([*safe_reasons, "receipt_finalization_failed"]))
    return _result(
        success=False,
        status="partial_failure",
        receipt_id=receipt_id,
        counts=counts,
        reason_codes=safe_reasons,
    )


def _new_receipt(
    *,
    receipt_id: str,
    job: Any,
    native_status: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "id": receipt_id,
        "receipt_version": 1,
        "kind": "processed_source_cleanup",
        "status": "in_progress",
        "project_name": job.project_name,
        "reason": "processed_source_cleanup",
        "reason_codes": _safe_reason_codes(reason_codes),
        "requested_at": _utc_now(),
        "completed_at": None,
        "scope": {
            "job_id_sha256": _digest(job.id),
            "source_id_sha256": _digest(job.source_id),
            "session_id_sha256": _digest(job.session_id),
            "source_revision_sha256": _digest(job.source_revision),
        },
        "target_digests": [_digest(f"{job.source_id}@{job.source_revision}")],
        "native_cleanup": {"status": native_status},
        "actual_removal": {},
        "verification": {"passed": False, "remaining": {}},
    }


def begin_processed_source_cleanup(
    backend: LocalMemoryBackend,
    *,
    job_id: str,
    native_preview: dict[str, Any],
) -> dict[str, Any]:
    """Persist the content-free saga receipt before native source mutation."""

    job = backend.transcript_store.get_distill_job(job_id)
    if job is None or job.status != "completed":
        return {
            "success": False,
            "receipt_id": None,
            "reason_codes": [
                "distill_job_not_found"
                if job is None
                else "distill_job_not_completed"
            ],
        }
    try:
        backup_matches = count_managed_backup_observations(
            backend.data_dir,
            project_name=job.project_name,
            transcript_source_id=job.source_id,
        )
    except Exception:
        return {
            "success": False,
            "receipt_id": None,
            "reason_codes": ["managed_backup_probe_failed"],
        }
    if backup_matches:
        return {
            "success": False,
            "receipt_id": None,
            "reason_codes": ["managed_backup_contains_source_evidence"],
        }
    receipt_id = str(uuid4())
    receipt = _new_receipt(
        receipt_id=receipt_id,
        job=job,
        native_status="planned",
        reason_codes=_native_reason_codes(native_preview),
    )
    _add_revision_scope(backend, job, receipt)
    receipt["native_cleanup"] = {
        "status": "planned",
        "locator_sha256": str(native_preview.get("locator_sha256") or ""),
        "planned_actions": int(
            dict(native_preview.get("counts") or {}).get("planned", 0) or 0
        ),
    }
    try:
        backend.transcript_store.save_deletion_receipt(receipt)
    except Exception:
        return {
            "success": False,
            "receipt_id": None,
            "reason_codes": ["receipt_persistence_failed"],
        }
    return {
        "success": True,
        "receipt_id": receipt_id,
        "reason_codes": [],
    }


def _add_revision_scope(
    backend: LocalMemoryBackend,
    job: Any,
    receipt: dict[str, Any],
) -> None:
    """Add every revision digest for the source without persisting raw ids."""

    revisions = backend.transcript_store.list_revisions(job.source_id)
    scope = receipt.get("scope")
    if not isinstance(scope, dict):
        scope = {}
        receipt["scope"] = scope
    scope["source_revision_sha256s"] = sorted(
        {_digest(revision.source_revision) for revision in revisions}
    )
    receipt["target_digests"] = sorted(
        {_digest(f"{job.source_id}@{revision.source_revision}") for revision in revisions}
    )


def _native_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"deleted", "succeeded", "success"} or payload.get("deleted") is True:
        return "deleted"
    if status in {"unsupported", "unsupported_source"}:
        return "unsupported"
    return "partial_failure"


def _find_deletion_receipt(
    backend: LocalMemoryBackend,
    project_name: str,
    receipt_id: str,
) -> dict[str, Any] | None:
    for receipt in backend.transcript_store.list_deletion_audit(
        project_name=project_name
    ):
        if str(receipt.get("id") or "") == receipt_id:
            return receipt
    return None


def _native_reason_codes(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("reason_codes")
    values = raw if isinstance(raw, list) else [payload.get("reason_code")]
    return _safe_reason_codes(str(value) for value in values if value)


def _safe_reason_codes(values: Any) -> list[str]:
    return [
        str(value)
        for value in values
        if _SAFE_REASON_CODE.fullmatch(str(value))
    ]


def _failure_code(exc: Exception) -> str:
    return f"cleanup_{type(exc).__name__.lower()}"


def _observation_matches(payload: dict[str, Any], job: Any) -> bool:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return bool(
        str(metadata.get("project_name") or "") == job.project_name
        and str(metadata.get("transcript_source_id") or "") == job.source_id
        and str(metadata.get("source_revision") or "") == job.source_revision
    )


def _payload_matches_job(
    payload: dict[str, Any],
    job: Any,
    observation_ids: set[str],
    *,
    allow_legacy_session_fallback: bool,
) -> bool:
    if str(payload.get("distill_job_id") or "") == job.id:
        return True
    source_value = str(payload.get("source") or "")
    if source_value in {*observation_ids, job.source_id, f"distill-job:{job.id}"}:
        return True
    if (
        str(payload.get("transcript_source_id") or payload.get("source_id") or "")
        == job.source_id
        and str(payload.get("source_revision") or "") == job.source_revision
    ):
        return True
    job_session_id = str(job.session_id or "")
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        refs = provenance.get("observation_ids")
        if isinstance(refs, list) and observation_ids.intersection(map(str, refs)):
            return True
        if (
            str(
                provenance.get("transcript_source_id")
                or provenance.get("source_id")
                or ""
            )
            == job.source_id
            and str(provenance.get("source_revision") or "") == job.source_revision
        ):
            return True
    if not allow_legacy_session_fallback or not job_session_id:
        return False
    return bool(
        str(payload.get("session_id") or "") == job_session_id
        or str(payload.get("source_session_id") or "") == job_session_id
        or (
            isinstance(provenance, dict)
            and str(provenance.get("session_id") or "") == job_session_id
        )
    )


def _legacy_session_fallback_allowed(
    backend: LocalMemoryBackend,
    job: Any,
) -> bool:
    """Use session-only provenance only when it identifies one logical source."""

    job_session_id = str(job.session_id or "")
    if not job_session_id:
        return False
    source_ids = {
        source.id
        for source in backend.transcript_store.list_sources(
            project_name=job.project_name,
            limit=100_000,
        )
        if source.session_id == job_session_id
    }
    return source_ids == {job.source_id}


def _reference_ids(payload: dict[str, Any]) -> set[str]:
    scalar_fields = {
        "distill_job_id", "session_id", "source_session_id", "source_candidate_id",
        "source", "observation_id", "signal_id", "truth_id", "candidate_id",
        "entry_id", "created_entry_id", "target_id", "replacement_id",
        "target_a_id", "target_b_id", "source_entity", "target_entity",
    }
    list_fields = {
        "observation_ids", "signal_ids", "evidence_ids", "evidence_signal_ids",
        "selected_signal_ids", "selected_ids", "source_ids", "source_truth_ids",
    }
    refs: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in scalar_fields and child is not None and child != "":
                    refs.add(str(child))
                elif key in list_fields and isinstance(child, list):
                    refs.update(
                        str(item)
                        for item in child
                        if not isinstance(item, (dict, list))
                        and item is not None
                        and item != ""
                    )
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(payload)
    return refs


def _payload_has_raw_provenance(payload: dict[str, Any]) -> bool:
    if payload.get("distill_job_id"):
        return True
    if payload.get("session_id") or payload.get("source_session_id"):
        return True
    if payload.get("source") not in {None, "", "manual", "processed_source_pruned"}:
        return True
    provenance = payload.get("provenance")
    return isinstance(provenance, dict) and bool(
        provenance.get("session_id") or provenance.get("observation_ids")
    )


def _pruned_provenance(receipt_id: str) -> dict[str, str]:
    return {
        "evidence_state": "source_pruned",
        "cleanup_receipt_id": receipt_id,
    }


def _structured_store(backend: LocalMemoryBackend) -> LocalStructuredStore:
    store = backend.structured_store
    if not isinstance(store, LocalStructuredStore):
        raise TypeError("processed-source cleanup requires the local structured store")
    return store


def _verbatim_store(backend: LocalMemoryBackend) -> LocalVerbatimStore:
    store = backend.verbatim_store
    if not isinstance(store, LocalVerbatimStore):
        raise TypeError("processed-source cleanup requires the local verbatim store")
    return store


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(
    *,
    success: bool,
    status: str,
    receipt_id: str | None,
    counts: dict[str, int],
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "success": success,
        "status": status,
        "receipt_id": receipt_id,
        "counts": counts,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


__all__ = [
    "begin_processed_source_cleanup",
    "cleanup_processed_source",
    "retry_retained_source_cleanups",
]
