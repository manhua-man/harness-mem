"""Privacy erasure and transcript-retention orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from typing import Any
from uuid import uuid4

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.derived_index import DerivedIndex

_STRUCTURED_COLLECTIONS = (
    "memory_entries",
    "rule_candidates",
    "procedural_candidates",
    "relation_facts",
    "confirmed_rules",
    "skills",
    "supersede_candidates",
    "merge_suggestion_candidates",
    "stale_truth_suggestion_candidates",
    "task_handoffs",
    "retrieval_signals",
    "metabolism_runs",
    "dream_runs",
)
_CANDIDATE_COLLECTIONS = {
    "memory_entries",
    "rule_candidates",
    "procedural_candidates",
    "relation_facts",
    "supersede_candidates",
    "merge_suggestion_candidates",
    "stale_truth_suggestion_candidates",
}
_SAFE_RECEIPT_REASONS = frozenset({"user_requested_erasure", "privacy_request"})
_RETENTION_REASON_RE = re.compile(r"^retention_expired:\d+d$")


async def plan_hard_delete(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    session_id: str | None = None,
    source_id: str | None = None,
    before: datetime | None = None,
) -> dict[str, Any]:
    """Build a complete evidence/derived-data erasure plan without mutations."""

    _validate_delete_scope(session_id=session_id, source_id=source_id, before=before)

    ledger = backend.transcript_store.plan_hard_delete(
        project_name=project_name,
        session_id=session_id,
        source_id=source_id,
        before=before,
    )
    selected_revisions = {
        (str(source), str(revision)) for source, revision in ledger["revision_keys"]
    }
    selected_sources = set(ledger["source_ids"])
    selected_sessions = set(ledger["session_ids"])
    if session_id:
        selected_sessions.add(session_id)
    # A session id is only a safe provenance fallback when the caller asked to
    # erase the whole session. Retention and revision/source-scoped erasure may
    # select an older revision while a newer revision of the same session must
    # remain readable.
    session_fallback_ids = (
        selected_sessions
        if session_id is not None and source_id is None and before is None
        else set()
    )
    selected_jobs = set(ledger["job_ids"])

    verbatim_store = backend.verbatim_store
    if not isinstance(verbatim_store, LocalVerbatimStore):
        raise TypeError("hard delete requires the local verbatim store")
    observation_payloads = verbatim_store.list_record_payloads_for_lifecycle()
    observations = [
        _observation_lifecycle_fields(payload) for payload in observation_payloads
    ]
    observation_ids = {
        observation["id"]
        for observation in observations
        if observation["project_name"] == project_name
        and (
            (
                observation["transcript_source_id"]
                in selected_sources
                and (
                    observation["transcript_source_id"],
                    observation["source_revision"],
                )
                in selected_revisions
            )
            or (
                observation["session_id"] in session_fallback_ids
                and not observation["transcript_source_id"]
            )
        )
    }

    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    payloads_by_collection: dict[str, list[dict[str, Any]]] = {}
    for collection in _STRUCTURED_COLLECTIONS:
        payloads_by_collection[collection] = structured_store.list_record_payloads(
            collection,
            strict=True,
        )
    structured = _linked_structured_records(
        payloads_by_collection,
        project_name=project_name,
        job_ids=selected_jobs,
        session_ids=session_fallback_ids,
        observation_ids=observation_ids,
    )
    index_counts = _count_index_artifacts(
        backend,
        observation_ids=observation_ids,
        structured=structured,
    )
    return {
        **ledger,
        "observation_ids": sorted(observation_ids),
        "structured": structured,
        "index_counts": index_counts,
        "counts": {
            "revisions": ledger["revision_count"],
            "chunks": ledger["chunk_count"],
            "distill_jobs": len(ledger["job_ids"]),
            "observations": len(observation_ids),
            "candidates": sum(
                len(ids) for collection, ids in structured.items()
                if collection in _CANDIDATE_COLLECTIONS
            ),
            "structured_truth": sum(
                len(ids) for collection, ids in structured.items()
                if collection not in _CANDIDATE_COLLECTIONS
            ),
            "indexes": index_counts["entity_rows"],
            "index_artifacts": sum(index_counts.values()),
            "raw_bytes": ledger["raw_bytes"],
        },
    }


async def hard_delete(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    session_id: str | None = None,
    source_id: str | None = None,
    before: datetime | None = None,
    reason: str = "user_requested_erasure",
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or execute a complete local erasure, defaulting to dry-run."""

    plan = await plan_hard_delete(
        backend,
        project_name=project_name,
        session_id=session_id,
        source_id=source_id,
        before=before,
    )
    if not apply:
        return {"success": True, "applied": False, "plan": plan}
    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    requested_at = datetime.now(timezone.utc).isoformat()
    receipt_reason, receipt_reason_digest = _receipt_reason(reason)
    receipt_scope = _receipt_scope(
        session_id=session_id,
        source_id=source_id,
        before=before,
    )
    if source_id is not None and before is None:
        receipt_scope["source_identity_sha256"] = sorted(
            {
                _digest_identifier(
                    f"{str(revision.get('client') or '')}\x1f"
                    f"{str(revision.get('session_id') or '')}"
                )
                for revision in plan["revisions"]
                if revision.get("client") and revision.get("session_id")
            }
        )
    receipt = {
        "id": str(uuid4()),
        "receipt_version": 1,
        "kind": "hard_delete",
        "status": "in_progress",
        "project_name": project_name,
        "scope": receipt_scope,
        "reason": receipt_reason,
        **(
            {"reason_sha256": receipt_reason_digest}
            if receipt_reason_digest is not None
            else {}
        ),
        "requested_at": requested_at,
        "completed_at": None,
        "plan_counts": dict(plan["counts"]),
        "actual_removal": {},
        "verification": {"passed": False, "remaining": {}},
        "target_digests": [
            _digest_identifier(f"{source}@{revision}")
            for source, revision in plan["revision_keys"]
        ],
    }
    try:
        backend.transcript_store.save_deletion_receipt(receipt)
    except Exception as exc:
        return {
            "success": False,
            "applied": False,
            "reason": "receipt_persistence_failed",
            "error_type": type(exc).__name__,
            "plan": plan,
        }

    if not any(
        value
        for key, value in plan["counts"].items()
        if key != "raw_bytes"
    ):
        receipt.update(
            {
                "status": "skipped",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "actual_removal": {
                    key: 0 for key in plan["counts"]
                },
                "counts": {key: 0 for key in plan["counts"]},
                "verification": {"passed": True, "remaining": {}},
            }
        )
        try:
            backend.transcript_store.save_deletion_receipt(receipt)
        except Exception as exc:
            return {
                "success": False,
                "applied": False,
                "skipped": True,
                "reason": "receipt_finalization_failed",
                "error_type": type(exc).__name__,
                "receipt_persisted": False,
                "plan": plan,
                "audit": receipt,
                "receipt": receipt,
            }
        return {
            "success": True,
            "applied": False,
            "skipped": True,
            "reason": "no_matching_data",
            "plan": plan,
            "audit": receipt,
            "receipt": receipt,
        }

    actual = {
        "revisions": 0,
        "chunks": 0,
        "distill_jobs": 0,
        "observations": 0,
        "candidates": 0,
        "structured_truth": 0,
        "indexes": 0,
        "index_artifacts": 0,
        "raw_bytes": 0,
    }
    operation = "structured_records"
    try:
        for collection, entity_ids in plan["structured"].items():
            for entity_id in entity_ids:
                deleted = int(structured_store.hard_delete_record(collection, entity_id))
                if collection in _CANDIDATE_COLLECTIONS:
                    actual["candidates"] += deleted
                else:
                    actual["structured_truth"] += deleted

        operation = "observations"
        for observation_id in plan["observation_ids"]:
            actual["observations"] += int(
                await backend.verbatim_store.delete(observation_id)
            )

        operation = "transcript_ledger"
        audit = backend.transcript_store.hard_delete_revisions(
            plan["revision_keys"],
            project_name=project_name,
            reason=receipt_reason,
            audit_counts={
                "observations": actual["observations"],
                "candidates": actual["candidates"],
                "structured_truth": actual["structured_truth"],
            },
            receipt=receipt,
        )
        for key in ("revisions", "chunks", "distill_jobs"):
            actual[key] = int(audit["counts"].get(key, 0))

        operation = "post_delete_verification"
        remaining = await _verify_hard_delete(backend, plan)
        _reconcile_actual_removal(actual, plan["counts"], remaining)
        passed = not any(remaining.values())
        receipt.update(
            {
                "status": "succeeded" if passed else "partial_failure",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "counts": dict(actual),
                "actual_removal": actual,
                "verification": {"passed": passed, "remaining": remaining},
            }
        )
        backend.transcript_store.save_deletion_receipt(receipt)
        return {
            "success": passed,
            "applied": True,
            "partial": not passed,
            "plan": plan,
            "audit": receipt,
            "receipt": receipt,
        }
    except Exception as exc:
        verification_error_type: str | None
        try:
            remaining = await _verify_hard_delete(backend, plan)
        except Exception as verification_exc:
            remaining = {"verification_errors": 1}
            verification_error_type = type(verification_exc).__name__
        else:
            verification_error_type = None
        _reconcile_actual_removal(actual, plan["counts"], remaining)
        receipt.update(
            {
                "status": "partial_failure",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "counts": dict(actual),
                "actual_removal": actual,
                "verification": {"passed": False, "remaining": remaining},
                "failure": {
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    **(
                        {"verification_error_type": verification_error_type}
                        if verification_error_type
                        else {}
                    ),
                },
            }
        )
        receipt_persisted = True
        try:
            backend.transcript_store.save_deletion_receipt(receipt)
        except Exception:
            # The initial in_progress receipt is still durable and cannot be
            # mistaken for a successful erasure.
            receipt_persisted = False
        return {
            "success": False,
            "applied": True,
            "partial": True,
            "reason": "hard_delete_partial_failure",
            "error_type": type(exc).__name__,
            "receipt_persisted": receipt_persisted,
            "plan": plan,
            "audit": receipt,
            "receipt": receipt,
        }


async def enforce_transcript_retention(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    retention_days: int,
    apply: bool = False,
) -> dict[str, Any]:
    """Erase revisions older than a configured duration; zero means forever."""

    if retention_days <= 0:
        return {
            "success": True,
            "applied": False,
            "skipped": True,
            "reason": "retention_disabled",
        }
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return await hard_delete(
        backend,
        project_name=project_name,
        before=cutoff,
        reason=f"retention_expired:{retention_days}d",
        apply=apply,
    )


def _payload_is_directly_linked(
    payload: dict[str, Any],
    *,
    job_ids: set[str],
    session_ids: set[str],
    observation_ids: set[str],
) -> bool:
    if str(payload.get("distill_job_id") or "") in job_ids:
        return True
    if str(payload.get("session_id") or "") in session_ids:
        return True
    if str(payload.get("source_session_id") or "") in session_ids:
        return True
    if str(payload.get("source") or "") in observation_ids:
        return True
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return False
    if str(provenance.get("session_id") or "") in session_ids:
        return True
    refs = provenance.get("observation_ids")
    return isinstance(refs, list) and bool(observation_ids.intersection(map(str, refs)))


def _observation_lifecycle_fields(payload: dict[str, Any]) -> dict[str, str]:
    """Extract only selector fields while retaining compacted observations."""

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": str(payload.get("id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "project_name": str(metadata.get("project_name") or ""),
        "transcript_source_id": str(metadata.get("transcript_source_id") or ""),
        "source_revision": str(metadata.get("source_revision") or ""),
    }


def _linked_structured_records(
    payloads_by_collection: dict[str, list[dict[str, Any]]],
    *,
    project_name: str,
    job_ids: set[str],
    session_ids: set[str],
    observation_ids: set[str],
    preselected: dict[str, set[str]] | None = None,
    seed_entity_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    """Build the explicit provenance/reference closure for private data.

    This deliberately follows schema-defined identifier fields rather than
    scanning arbitrary strings.  It therefore catches governance candidates,
    retrieval evidence, and maintenance ledgers without deleting unrelated
    records that merely contain the same text.
    """

    selected: dict[str, set[str]] = {
        collection: set((preselected or {}).get(collection, set()))
        for collection in _STRUCTURED_COLLECTIONS
    }
    linked_ids = {
        *map(str, job_ids),
        *map(str, session_ids),
        *map(str, observation_ids),
        *map(str, seed_entity_ids or set()),
    }
    for entity_ids in selected.values():
        linked_ids.update(map(str, entity_ids))

    changed = True
    while changed:
        changed = False
        for collection in _STRUCTURED_COLLECTIONS:
            for payload in payloads_by_collection.get(collection, []):
                entity_id = str(payload.get("id") or "")
                if (
                    not entity_id
                    or str(payload.get("project_name") or "") != project_name
                    or entity_id in selected[collection]
                ):
                    continue
                if _payload_is_directly_linked(
                    payload,
                    job_ids=job_ids,
                    session_ids=session_ids,
                    observation_ids=observation_ids,
                ) or bool(_payload_reference_ids(payload).intersection(linked_ids)):
                    selected[collection].add(entity_id)
                    linked_ids.add(entity_id)
                    changed = True
    return {
        collection: sorted(entity_ids)
        for collection, entity_ids in selected.items()
        if entity_ids
    }


def _payload_reference_ids(payload: dict[str, Any]) -> set[str]:
    """Return schema-defined identifier references from one structured row."""

    references: set[str] = set()
    scalar_fields = {
        "distill_job_id",
        "session_id",
        "source_session_id",
        "source_candidate_id",
        "source",
        "observation_id",
        "signal_id",
        "truth_id",
        "candidate_id",
        "entry_id",
        "created_entry_id",
        "target_id",
        "replacement_id",
        "target_a_id",
        "target_b_id",
        "source_entity",
        "target_entity",
        "metabolism_run_id",
        "dream_run_id",
        "reflection_job_id",
    }
    list_fields = {
        "observation_ids",
        "signal_ids",
        "evidence_ids",
        "evidence_signal_ids",
        "selected_signal_ids",
        "selected_ids",
        "source_ids",
        "source_truth_ids",
        "supersedes",
        "superseded_by",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in scalar_fields and child is not None and child != "":
                    references.add(str(child))
                elif key in list_fields and isinstance(child, list):
                    references.update(
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
    return references


def _count_index_artifacts(
    backend: LocalMemoryBackend,
    *,
    observation_ids: set[str] | list[str],
    structured: dict[str, list[str]],
) -> dict[str, int]:
    """Count rebuildable rows that the selected canonical data owns."""

    verbatim_store = backend.verbatim_store
    if not isinstance(verbatim_store, LocalVerbatimStore):
        raise TypeError("hard delete requires the local verbatim store")
    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    main_rows = _count_sqlite_rows(
        verbatim_store.index,
        table="observations",
        column="id",
        entity_ids=observation_ids,
    )
    entry_ids = set(map(str, observation_ids))
    for collection, entity_ids in structured.items():
        main_rows += _count_sqlite_rows(
            structured_store.index,
            table=collection,
            column="id",
            entity_ids=entity_ids,
        )
        entry_ids.update(map(str, entity_ids))

    # Verbatim and structured indexes are separate SQLite databases.
    embedding_rows = sum(
        _count_sqlite_rows(
            index,
            table="vec_embeddings",
            column="entry_id",
            entity_ids=entry_ids,
        )
        for index in (verbatim_store.index, structured_store.index)
    )
    trigram_rows = _count_sqlite_rows(
        verbatim_store.index,
        table="observation_trigrams",
        column="observation_id",
        entity_ids=observation_ids,
    )
    return {
        "entity_rows": main_rows,
        "embedding_rows": embedding_rows,
        "trigram_rows": trigram_rows,
    }


def _count_sqlite_rows(
    index: DerivedIndex,
    *,
    table: str,
    column: str,
    entity_ids: set[str] | list[str],
) -> int:
    """Count selected index rows in bounded batches below SQLite limits."""

    ordered_ids = sorted(set(map(str, entity_ids)))
    total = 0
    with index.locked_connection() as conn:
        for offset in range(0, len(ordered_ids), 500):
            batch = ordered_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in batch)
            total += int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})",
                    tuple(batch),
                ).fetchone()[0]
            )
    return total


async def _verify_hard_delete(
    backend: LocalMemoryBackend,
    plan: dict[str, Any],
) -> dict[str, int]:
    before_value = plan.get("before")
    before = (
        datetime.fromisoformat(str(before_value))
        if before_value is not None
        else None
    )
    residual_plan = await plan_hard_delete(
        backend,
        project_name=str(plan["project_name"]),
        session_id=plan.get("session_id"),
        source_id=plan.get("source_id"),
        before=before,
    )
    revision_keys: list[tuple[str, str]] = sorted(
        {
            *((str(key[0]), str(key[1])) for key in plan["revision_keys"]),
            *(
                (str(key[0]), str(key[1]))
                for key in residual_plan["revision_keys"]
            ),
        }
    )
    job_ids = sorted({*map(str, plan["job_ids"]), *map(str, residual_plan["job_ids"])})
    remaining = backend.transcript_store.verify_hard_delete(
        revision_keys,
        job_ids=job_ids,
    )

    observation_ids = {
        *map(str, plan["observation_ids"]),
        *map(str, residual_plan["observation_ids"]),
    }
    remaining["observations"] = 0
    for observation_id in observation_ids:
        remaining["observations"] += int(
            await backend.verbatim_store.get(observation_id) is not None
        )

    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    payloads_by_collection = {
        collection: structured_store.list_record_payloads(collection, strict=True)
        for collection in _STRUCTURED_COLLECTIONS
    }
    preselected = {
        collection: {
            *map(str, plan["structured"].get(collection, [])),
            *map(str, residual_plan["structured"].get(collection, [])),
        }
        for collection in _STRUCTURED_COLLECTIONS
    }
    seed_entity_ids = {
        *observation_ids,
        *job_ids,
        *(
            str(entity_id)
            for entity_ids in preselected.values()
            for entity_id in entity_ids
        ),
    }
    verification_structured = _linked_structured_records(
        payloads_by_collection,
        project_name=str(plan["project_name"]),
        job_ids=set(job_ids),
        session_ids={
            str(value)
            for value in (plan.get("session_id"),)
            if value is not None
        },
        observation_ids=observation_ids,
        preselected={
            collection: {
                entity_id
                for entity_id in entity_ids
                if structured_store.record_payload_exists(collection, entity_id)
            }
            for collection, entity_ids in preselected.items()
        },
        seed_entity_ids=seed_entity_ids,
    )
    remaining["candidates"] = sum(
        len(entity_ids)
        for collection, entity_ids in verification_structured.items()
        if collection in _CANDIDATE_COLLECTIONS
    )
    remaining["structured_truth"] = sum(
        len(entity_ids)
        for collection, entity_ids in verification_structured.items()
        if collection not in _CANDIDATE_COLLECTIONS
    )
    index_counts = _count_index_artifacts(
        backend,
        observation_ids=observation_ids,
        structured=verification_structured,
    )
    remaining["indexes"] = index_counts["entity_rows"]
    remaining["index_artifacts"] = sum(index_counts.values())
    return remaining


def _validate_delete_scope(
    *,
    session_id: str | None,
    source_id: str | None,
    before: datetime | None,
) -> None:
    """Prevent an accidental project-wide wipe through the core API."""

    if session_id is None and source_id is None and before is None:
        raise ValueError(
            "hard delete requires session_id, source_id, or before; "
            "project-wide erasure is not an implicit operation"
        )


def _digest_identifier(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _receipt_reason(reason: str) -> tuple[str, str | None]:
    """Keep standard reason codes readable and hash arbitrary operator text."""

    normalized = str(reason or "").strip()
    if normalized in _SAFE_RECEIPT_REASONS or _RETENTION_REASON_RE.fullmatch(normalized):
        return normalized, None
    return "custom_reason", _digest_identifier(normalized)


def _reconcile_actual_removal(
    actual: dict[str, int],
    planned: dict[str, int],
    remaining: dict[str, Any],
) -> None:
    """Derive observed removals from the post-delete state when available."""

    for key in (
        "revisions",
        "chunks",
        "distill_jobs",
        "observations",
        "candidates",
        "structured_truth",
        "indexes",
        "index_artifacts",
    ):
        if key not in remaining:
            continue
        actual[key] = max(0, int(planned.get(key, 0)) - int(remaining[key]))
    if actual.get("revisions") == int(planned.get("revisions", 0)):
        actual["raw_bytes"] = int(planned.get("raw_bytes", 0))


def _receipt_scope(
    *,
    session_id: str | None,
    source_id: str | None,
    before: datetime | None,
) -> dict[str, Any]:
    """Describe erasure selectors without persisting private identifiers."""

    scope: dict[str, Any] = {}
    if session_id is not None:
        scope["session_id_sha256"] = _digest_identifier(session_id)
    if source_id is not None:
        scope["source_id_sha256"] = _digest_identifier(source_id)
    if before is not None:
        cutoff = before if before.tzinfo else before.replace(tzinfo=timezone.utc)
        scope["before"] = cutoff.astimezone(timezone.utc).isoformat()
    return scope


__all__ = [
    "enforce_transcript_retention",
    "hard_delete",
    "plan_hard_delete",
]
