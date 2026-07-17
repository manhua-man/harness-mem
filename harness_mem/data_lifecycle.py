"""Privacy erasure and transcript-retention orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore

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


async def plan_hard_delete(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    session_id: str | None = None,
    source_id: str | None = None,
    before: datetime | None = None,
) -> dict[str, Any]:
    """Build a complete evidence/derived-data erasure plan without mutations."""

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

    observations = await backend.verbatim_store.list(limit=100_000)
    observation_ids = {
        observation.id
        for observation in observations
        if observation.metadata.get("project_name") == project_name
        and (
            (
                str(observation.metadata.get("transcript_source_id") or "")
                in selected_sources
                and (
                    str(observation.metadata.get("transcript_source_id") or ""),
                    str(observation.metadata.get("source_revision") or ""),
                )
                in selected_revisions
            )
            or (
                observation.session_id in session_fallback_ids
                and not observation.metadata.get("transcript_source_id")
            )
        )
    }

    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    structured: dict[str, list[str]] = {collection: [] for collection in _STRUCTURED_COLLECTIONS}
    direct_candidate_ids: set[str] = set()
    payloads_by_collection: dict[str, list[dict[str, Any]]] = {}
    for collection in _STRUCTURED_COLLECTIONS:
        payloads = structured_store.list_record_payloads(collection)
        payloads_by_collection[collection] = payloads
        for payload in payloads:
            entity_id = str(payload.get("id") or "")
            if not entity_id or str(payload.get("project_name") or "") != project_name:
                continue
            if _payload_is_directly_linked(
                payload,
                job_ids=selected_jobs,
                session_ids=session_fallback_ids,
                observation_ids=observation_ids,
            ):
                structured[collection].append(entity_id)
                if collection in _CANDIDATE_COLLECTIONS:
                    direct_candidate_ids.add(entity_id)

    # Confirmed rules and generated skills retain a source-candidate edge even
    # after promotion.  Erasure follows that edge so private candidate content
    # cannot survive merely because its status changed.
    for collection in ("confirmed_rules", "skills"):
        for payload in payloads_by_collection[collection]:
            entity_id = str(payload.get("id") or "")
            if (
                entity_id
                and str(payload.get("project_name") or "") == project_name
                and str(payload.get("source_candidate_id") or "") in direct_candidate_ids
            ):
                structured[collection].append(entity_id)

    structured = {
        collection: sorted(set(entity_ids))
        for collection, entity_ids in structured.items()
        if entity_ids
    }
    return {
        **ledger,
        "observation_ids": sorted(observation_ids),
        "structured": structured,
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
    if not any(
        value
        for key, value in plan["counts"].items()
        if key != "raw_bytes"
    ):
        return {
            "success": True,
            "applied": False,
            "skipped": True,
            "reason": "no_matching_data",
            "plan": plan,
        }

    structured_store = backend.structured_store
    if not isinstance(structured_store, LocalStructuredStore):
        raise TypeError("hard delete requires the local structured store")
    structured_deleted = 0
    for collection, entity_ids in plan["structured"].items():
        for entity_id in entity_ids:
            structured_deleted += int(
                structured_store.hard_delete_record(collection, entity_id)
            )
    observations_deleted = 0
    for observation_id in plan["observation_ids"]:
        observations_deleted += int(await backend.verbatim_store.delete(observation_id))

    audit_counts = {
        "observations": observations_deleted,
        "structured": structured_deleted,
    }
    audit = backend.transcript_store.hard_delete_revisions(
        plan["revision_keys"],
        project_name=project_name,
        reason=reason,
        audit_counts=audit_counts,
    )
    return {
        "success": True,
        "applied": True,
        "plan": plan,
        "audit": audit,
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


__all__ = [
    "enforce_transcript_retention",
    "hard_delete",
    "plan_hard_delete",
]
