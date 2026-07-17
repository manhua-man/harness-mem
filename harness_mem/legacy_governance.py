"""One-time, review-preserving migration for literal legacy ``accepted`` rows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, cast

from harness_mem.event_log import StateEventType, append_state_event
from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS, is_readable_truth
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


LEGACY_GOVERNANCE_MIGRATION_VERSION = "legacy-accepted-v1"
_COLLECTIONS = ("memory_entries", "relation_facts", "rule_candidates")


async def migrate_legacy_accepted(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or move accepted rows to pending/superseded without creating truth."""

    store = cast(LocalStructuredStore, backend.structured_store)
    payloads = {
        collection: [
            payload
            for payload in store.list_record_payloads(collection)
            if _project_name(payload) == project_name
        ]
        for collection in (*_COLLECTIONS, "confirmed_rules")
    }
    plans: list[dict[str, Any]] = []
    for collection in _COLLECTIONS:
        for payload in payloads[collection]:
            if str(payload.get("status") or "") != LEGACY_ACCEPTED_STATUS:
                continue
            equivalent = _equivalent_current(
                collection,
                payload,
                payloads=payloads,
            )
            plans.append(
                {
                    "collection": collection,
                    "id": str(payload.get("id") or ""),
                    "from_status": LEGACY_ACCEPTED_STATUS,
                    "target_status": "superseded" if equivalent else "pending",
                    "equivalent_current_id": str(equivalent.get("id")) if equivalent else None,
                    "reason": (
                        "equivalent current truth already exists; preserve as historical"
                        if equivalent
                        else "no current equivalent; return to Hm Review as pending"
                    ),
                }
            )
    plans.sort(key=lambda item: (item["collection"], item["id"]))

    applied: list[dict[str, Any]] = []
    if apply:
        migrated_at = datetime.now(timezone.utc).isoformat()
        for item in plans:
            collection = item["collection"]
            entity_id = item["id"]
            current = store.read_record_payload(collection, entity_id)
            if str(current.get("status") or "") != LEGACY_ACCEPTED_STATUS:
                continue
            previous_valid_to = current.get("valid_to")
            previous_superseded_by = list(current.get("superseded_by") or [])
            target = item["target_status"]
            current["status"] = target
            current["legacy_accepted_migration"] = {
                "version": LEGACY_GOVERNANCE_MIGRATION_VERSION,
                "migrated_at": migrated_at,
                "previous_status": LEGACY_ACCEPTED_STATUS,
                "decision": target,
                "equivalent_current_id": item["equivalent_current_id"],
            }
            index_fields: dict[str, Any] = {"status": target}
            if target == "superseded":
                superseded_by = list(current.get("superseded_by") or [])
                equivalent_id = item["equivalent_current_id"]
                if equivalent_id and equivalent_id not in superseded_by:
                    superseded_by.append(equivalent_id)
                current["superseded_by"] = superseded_by
                current["valid_to"] = migrated_at
                index_fields.update(
                    {"superseded_by": superseded_by, "valid_to": migrated_at}
                )
            store.write_record_payload(collection, entity_id, current)
            await asyncio.to_thread(
                store.index.update,
                collection,
                entity_id,
                index_fields,
            )
            append_state_event(
                backend.data_dir,
                event_type=(
                    StateEventType.SUPERSEDE_COMPLETED
                    if target == "superseded"
                    else StateEventType.CANDIDATE_REVIEWED
                ),
                project_name=project_name,
                target_kind=collection,
                target_id=entity_id,
                status=target,
                source_surface="maintenance.migrate-legacy-accepted",
                actor="operator",
                payload={
                    "migration_version": LEGACY_GOVERNANCE_MIGRATION_VERSION,
                    "previous_status": LEGACY_ACCEPTED_STATUS,
                    "equivalent_current_id": item["equivalent_current_id"],
                    "automatic_truth_promotion": False,
                    "undo": {
                        "status": LEGACY_ACCEPTED_STATUS,
                        "valid_to": previous_valid_to,
                        "superseded_by": previous_superseded_by,
                    },
                },
            )
            applied.append(item)

    by_target = {
        status: sum(item["target_status"] == status for item in plans)
        for status in ("pending", "superseded")
    }
    return {
        "migration_version": LEGACY_GOVERNANCE_MIGRATION_VERSION,
        "project_name": project_name,
        "dry_run": not apply,
        "found": len(plans),
        "planned": len(plans),
        "applied": len(applied),
        "by_target": by_target,
        "automatic_truth_promotion": False,
        "review_required": by_target["pending"],
        "items": plans,
        "next_step": "$hm-review" if by_target["pending"] else None,
    }


def _equivalent_current(
    collection: str,
    source: dict[str, Any],
    *,
    payloads: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    candidates = (
        payloads["confirmed_rules"]
        if collection == "rule_candidates"
        else payloads[collection]
    )
    source_key = _semantic_key(collection, source)
    for candidate in candidates:
        if str(candidate.get("id") or "") == str(source.get("id") or ""):
            continue
        if not is_readable_truth(str(candidate.get("status") or "")):
            continue
        if _semantic_key(collection, candidate) == source_key:
            return candidate
    return None


def _semantic_key(collection: str, payload: dict[str, Any]) -> tuple[str, ...]:
    if collection == "memory_entries":
        return (
            _text(payload.get("category")),
            _text(payload.get("memory_type")),
            _text(payload.get("content")),
        )
    if collection == "relation_facts":
        return (
            _text(payload.get("source_entity")),
            _text(payload.get("relation_type")),
            _text(payload.get("target_entity")),
            _text(payload.get("evidence")),
        )
    return (
        _text(payload.get("trigger")),
        _text(payload.get("pattern")),
    )


def _project_name(payload: dict[str, Any]) -> str | None:
    value = payload.get("project_name")
    return str(value) if value else None


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


__all__ = ["LEGACY_GOVERNANCE_MIGRATION_VERSION", "migrate_legacy_accepted"]
