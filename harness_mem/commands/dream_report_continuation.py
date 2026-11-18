"""One finite current-report recheck on an existing terminal maintenance account.

This owner binds metadata, leases and canonical checkpoints only. Normal Dream
source/proposal/final/commit owners still decide and perform every report edit.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_mem.autonomous.models import DREAM_SOURCE_RECHECK_CONTRACT
from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
from harness_mem.commands.dream_assimilation import _entry_version_snapshot
from harness_mem.commands.dream_source_coverage import (
    TERMINAL_TAKEOVER_CONTRACT, _assert_original_successors, _carrier_heartbeat, _digest,
    _original_final_output_bindings, _terminal_carrier,
    _terminal_fixed, pending_terminal_source_coverage_count,
)
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


CONTRACT = "terminal-report-recheck-v16"
_PIN = "terminal_report_origin_run_id"
_MANIFEST = "terminal_report_manifest"
_MANIFEST_HASH = "terminal_report_manifest_sha256"


def _original(run: Any) -> bool:
    cp = run.continuation
    return (run.status == "failed" and run.completed_at is not None and run.trigger_source == "ide_hook"
            and cp.get("version") == "dream-slices-v3"
            and not cp.get("terminal_source_coverage_origin_run_id") and not cp.get(_PIN))


def _attempts(run: Any) -> dict[str, Any]:
    return (run.continuation.get("terminal_coverage_takeover") or {}).get("report_attempts") or {}


def _shared_bound(origin: Any, *, needs_slice: bool) -> tuple[int, int, dict[str, Any]]:
    cp = origin.continuation
    count, maximum = cp.get("slice_count"), cp.get("max_slices")
    initial = cp.get("terminal_source_coverage_initial_count", 0)
    takeover = cp.get("terminal_coverage_takeover") or {}
    claims, extra = takeover.get("claims", {}), takeover.get("slice_count", 0)
    _require_origin(type(count) is int and type(maximum) is int and type(initial) is int and initial >= 0
        and maximum == len(cp.get("target_ids") or []) + 1 + 2 * initial
        and count >= 0 and isinstance(claims, dict) and type(extra) is int and extra == len(claims)
        and extra >= 0 and (count + extra < maximum if needs_slice else count + extra <= maximum),
        "terminal_report_original_slices_exhausted")
    if takeover:
        _require_origin(takeover.get("contract") == TERMINAL_TAKEOVER_CONTRACT
            and takeover.get("origin_fixed_sha256") == _terminal_fixed(origin),
            "terminal_report_origin_binding_changed")
    return count, maximum, claims


async def _current_reports(backend: Any, project_name: str) -> list[Any]:
    return sorted((row for row in await backend.structured_store.knowledge_store.list_entries(project_name)
                   if row.source_report is not None), key=lambda row: row.id)


def _account(entry: Any) -> str:
    report = entry.source_report
    return _digest({key: getattr(report, key) for key in (
        "speaker", "period", "session_id", "source_id", "source_revision")})


async def _target(backend: Any, entry: Any) -> dict[str, Any]:
    sources = await backend.structured_store.knowledge_store.list_sources(entry.id)
    descriptors = [{key: getattr(row, key) for key in (
        "id", "knowledge_id", "project_name", "source_kind", "locator", "content_sha256")} for row in sources]
    canonical = backend.structured_store._canonical
    raw = canonical.get_payload_json("knowledge_entries", entry.id)
    _require_origin(raw is not None, "terminal_report_current_entry_missing")
    snapshot = _entry_version_snapshot(entry)
    revision = backend.transcript_store.get_revision(entry.source_report.source_id, entry.source_report.source_revision)
    return {"id": entry.id, "version": snapshot["version"],
        "semantic_sha256": _digest({key: snapshot[key] for key in ("title", "statement", "topic_path", "source_report")}),
        "payload_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "source_membership_sha256": _digest(sorted(descriptors, key=lambda row: row["id"])),
        "source_id": entry.source_report.source_id, "source_revision": entry.source_report.source_revision,
        "account_sha256": _account(entry),
        "source_ledger_sha256": _digest(revision.model_dump(mode="json")) if revision is not None else None}


async def bound_terminal_report_origin(
    backend: Any, *, project_name: str, project_root: str | Path, config: Any,
    host_client: str, origin_run_id: str | None = None, require_idle: bool = True,
) -> tuple[Any, str, str, str]:
    """Select once by real task ancestry, never by which account has credit."""
    recent = await backend.structured_store.list_dream_runs(project_name, limit=200)
    if require_idle:
        _require_origin(not recent or recent[0].status != "continuing", "terminal_report_current_continuation_exists")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
        for job in backend.reflection_job_store.list(project_name=project_name, status="processing", kind="dream"):
            stamp = job.updated_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            _require_origin(stamp < cutoff, "terminal_report_processing_active")
        _require_origin(not await pending_terminal_source_coverage_count(backend, project_name=project_name),
                        "terminal_report_source_coverage_pending")
    claimed_origins = [run.id for run in recent if any(
        row.get("contract") == CONTRACT for row in _attempts(run).values())]
    if origin_run_id is not None and claimed_origins:
        _require_origin(set(claimed_origins) == {origin_run_id}, "terminal_report_account_owner_changed")
    if require_idle:
        _require_origin(not claimed_origins, "terminal_report_contract_already_attempted")
    originals = [run for run in recent if _original(run)
                 and (origin_run_id is None or run.id == origin_run_id)]
    _require_origin(bool(originals), "no_terminal_report_origin")
    reports = {entry.id for entry in await _current_reports(backend, project_name)}
    _require_origin(bool(reports) or any(_attempts(run) for run in originals), "no_terminal_report_origin")
    # Current explicit project maintenance authorizes the new typed-report set.
    # A former selector's execution manifest is neither permission nor a way
    # to shop for an older account when the selected original lacks credit.
    origin = originals[0]
    # Selection precedes all account checks: failures never fall through to a
    # different generation, host or completed-source task with spare credit.
    _run, generation, trigger = await _bound_source_account(backend, run=origin,
        project_name=project_name, project_root=str(project_root), config=config, host_client=host_client,
        require_remaining=require_idle)
    _shared_bound(origin, needs_slice=require_idle)
    prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
    jobs = {note[len(prefix):].strip() for note in origin.notes or [] for prefix in prefixes if note.startswith(prefix)}
    _require_origin(len(jobs) == 1, "continuation_source_binding_missing")
    return origin, generation, trigger, next(iter(jobs))


async def report_manifest(backend: Any, origin: Any, *, project_name: str,
                          project_root: str | Path) -> dict[str, Any]:
    """Freeze current typed reports; the old execution manifest is not permission."""
    _require_origin(_original(origin) and origin.project_name == project_name, "terminal_report_origin_invalid")
    recent = await backend.structured_store.list_dream_runs(project_name, limit=200)
    _require_origin(not any(row.get("contract") == CONTRACT for run in recent for row in _attempts(run).values()),
                    "terminal_report_contract_already_attempted")
    count, maximum, claims = _shared_bound(origin, needs_slice=True)
    targets = [await _target(backend, entry) for entry in await _current_reports(backend, project_name)]
    _require_origin(bool(targets), "terminal_report_manifest_empty")
    return {"contract": CONTRACT, "semantic_contract": DREAM_SOURCE_RECHECK_CONTRACT,
        "origin_run_id": origin.id, "project_name": project_name,
        "project_root_sha256": _digest(str(Path(project_root).resolve())),
        "maintenance_scope": dict(origin.continuation["maintenance_scope"]), "targets": targets,
        "max_slices": min(len(targets) + 1, maximum - count - len(claims))}


def _remaining(carrier: Any) -> set[str]:
    cp = carrier.continuation
    done = set(cp.get("completed_signal_indexes") or [])
    return {identity for index, signal in enumerate(cp.get("signals") or []) if index not in done
            for identity in signal.get("target_ids") or []}


async def _validate_manifest(backend: Any, origin: Any, carrier: Any, *, project_root: str | Path) -> dict[str, Any]:
    cp = carrier.continuation
    manifest = cp.get(_MANIFEST)
    _require_origin(isinstance(manifest, dict) and manifest.get("contract") == CONTRACT
        and manifest.get("semantic_contract") == DREAM_SOURCE_RECHECK_CONTRACT
        and manifest.get("origin_run_id") == origin.id and cp.get(_PIN) == origin.id
        and manifest.get("project_name") == carrier.project_name == origin.project_name
        and manifest.get("project_root_sha256") == _digest(str(Path(project_root).resolve()))
        and not cp.get("terminal_source_coverage_origin_run_id")
        and manifest.get("maintenance_scope") == origin.continuation.get("maintenance_scope")
        and cp.get("maintenance_scope") == manifest.get("maintenance_scope")
        and cp.get(_MANIFEST_HASH) == _digest(manifest), "terminal_report_manifest_binding_changed")
    targets = manifest.get("targets")
    _require_origin(isinstance(targets, list) and bool(targets)
        and all(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] for row in targets)
        and len({row.get("id") for row in targets}) == len(targets)
        and cp.get("target_ids") == [row["id"] for row in targets]
        and type(manifest.get("max_slices")) is int and 0 < manifest["max_slices"] <= len(targets) + 1
        and cp.get("max_slices") == manifest.get("max_slices")
        and isinstance(cp.get("signals"), list)
        and [row.get("target_ids") for row in cp["signals"]] == [[row["id"]] for row in targets],
        "terminal_report_manifest_targets_changed")
    completed = cp.get("completed_signal_indexes", [])
    _require_origin(isinstance(completed, list) and all(type(index) is int and 0 <= index < len(targets)
        for index in completed) and len(set(completed)) == len(completed), "terminal_report_progress_invalid")
    store = backend.structured_store.knowledge_store
    pending = _remaining(carrier)
    for frozen in targets:
        entry = await store.get_entry(frozen["id"], project_name=carrier.project_name)
        if frozen["id"] not in pending:
            applied = [item for item in carrier.items if item.source_id == frozen["id"]
                       and item.final_action == "applied" and item.result.get("truth_change") in {"refine", "replace"}]
            if applied:
                _require_origin(entry is None, "terminal_report_committed_predecessor_current")
                identities = applied[-1].result.get("truth_ids") or []
                _require_origin(bool(identities) and len(set(identities)) == len(identities), "terminal_report_successor_missing")
                successors = []
                for identity in identities:
                    successor = await store.get_entry(identity, project_name=carrier.project_name)
                    _require_origin(successor is not None and successor.source_report is not None
                        and _account(successor) == frozen["account_sha256"]
                        and successor.title == successor.source_report.render_title()
                        and successor.statement == successor.source_report.render_statement(), "terminal_report_successor_changed")
                    successors.append(successor)
                proofs = _original_final_output_bindings(carrier, frozen["id"])
                _require_origin(bool(proofs) and all(any(row.get("id") == frozen["id"]
                    and row.get("version") == frozen["version"] for row in proof.get("predecessors") or [])
                    for proof in proofs), "terminal_report_successor_receipt_changed")
                _assert_original_successors(carrier, applied[-1], {"successor_entries": successors})
                continue
        _require_origin(entry is not None and entry.source_report is not None, "terminal_report_current_entry_changed")
        current = await _target(backend, entry)
        keys = [key for key in frozen if key != "payload_sha256"]
        _require_origin(all(current.get(key) == frozen.get(key) for key in keys),
                        "terminal_report_current_version_or_sources_changed")
        if frozen["id"] in pending:
            _require_origin(current["payload_sha256"] == frozen["payload_sha256"], "terminal_report_current_payload_changed")
    return manifest


async def bound_report_child(
    backend: Any, *, project_name: str, project_root: str | Path, config: Any, host_client: str,
    child_run_id: str, origin_run_id: str | None = None, require_remaining: bool = True,
    exhausted_bookkeeping: bool = False,
) -> tuple[Any, str, str]:
    """Resume only the frozen child and its original report attempt/account."""
    child = await backend.structured_store.get_dream_run(child_run_id)
    _require_origin(child is not None and child.project_name == project_name and child.status == "continuing",
                    "terminal_report_child_not_resumable")
    recent = await backend.structured_store.list_dream_runs(project_name, limit=1)
    _require_origin(bool(recent) and recent[0].id == child.id, "continuation_superseded")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
    for job in backend.reflection_job_store.list(project_name=project_name, status="processing", kind="dream"):
        stamp = job.updated_at if job.updated_at.tzinfo is not None else job.updated_at.replace(tzinfo=timezone.utc)
        _require_origin(stamp < cutoff, "continuation_processing_active")
    pin = child.continuation.get(_PIN)
    _require_origin(isinstance(pin, str) and (origin_run_id is None or pin == origin_run_id),
                    "terminal_report_child_origin_changed")
    origin, generation, trigger, _job = await bound_terminal_report_origin(backend, project_name=project_name,
        project_root=project_root, config=config, host_client=host_client, origin_run_id=pin, require_idle=False)
    manifest = await _validate_manifest(backend, origin, child, project_root=project_root)
    attempt = _attempts(origin).get(_digest(manifest))
    _require_origin(isinstance(attempt, dict) and attempt.get("carrier_run_id") == child.id
        and attempt.get("status") in {"claimed", "in_progress", "continuing"}, "terminal_report_child_attempt_closed")
    needs_native = bool(_remaining(child))
    _shared_bound(origin, needs_slice=needs_native and not exhausted_bookkeeping)
    if needs_native:
        _require_origin(exhausted_bookkeeping or child.continuation["slice_count"] < child.continuation["max_slices"],
                        "terminal_report_child_slices_exhausted")
        await _bound_source_account(backend, run=origin, project_name=project_name, project_root=str(project_root),
            config=config, host_client=host_client, require_remaining=not exhausted_bookkeeping,
            require_exhausted=exhausted_bookkeeping)
    if exhausted_bookkeeping:
        _require_origin(needs_native, "terminal_report_exhausted_work_missing")
        _exhausted_owner(backend, origin, child, manifest, project_root=project_root)
    return child, generation, trigger


def _exhausted_owner(backend: Any, origin: Any, child: Any, manifest: dict[str, Any], *, project_root: str | Path) -> None:
    """Bind the already closed reflection and last existing claim, without a provider."""
    cp = child.continuation
    ordinal = cp.get("slice_count")
    _require_origin(type(ordinal) is int and 0 < ordinal <= manifest["max_slices"],
                    "terminal_report_carrier_slice_invalid")
    digest = _digest(manifest)
    claim = (origin.continuation.get("terminal_coverage_takeover") or {}).get("claims", {}).get(f"{child.id}:{ordinal}")
    _require_origin(isinstance(claim, dict) and all(claim.get(key) == value for key, value in {
        "kind": "report_recheck", "origin_run_id": origin.id, "carrier_run_id": child.id,
        "carrier_reflection_id": child.reflection_job_id, "manifest_sha256": digest, "attempt_id": digest,
    }.items()) and claim.get("status") in {"claimed", "in_progress", "continuing"},
        "terminal_report_bookkeeping_claim_changed")
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    jobs = {note.split(": ", 1)[1].strip() for note in origin.notes or []
            if note.startswith(("Hook session distill succeeded: ", "Hook session distill verified: "))}
    source_ids = [identity for identity in reflection.input_refs
                  if backend.transcript_store.get_distill_job(identity) is not None] if reflection else []
    _require_origin(reflection is not None and reflection.status in {"completed", "failed", "retryable"}
        and reflection.lease_owner is None and reflection.lease_until is None
        and (reflection.status != "retryable" or (reflection.phase == "metabolism"
            and reflection.completed_at is None and child.id in reflection.input_refs))
        and reflection.kind == "dream" and reflection.source == "ide_hook"
        and reflection.project_name == child.project_name
        and Path(reflection.project_root).resolve() == Path(project_root).resolve()
        and origin.id in reflection.input_refs and len(source_ids) == 1 and set(source_ids) == jobs,
        "terminal_report_bookkeeping_reflection_changed")
    job = backend.transcript_store.get_distill_job(source_ids[0])
    _require_origin(job.completed_chunk_count == job.expected_chunk_count
        and job.structural_audit.get("coverage") == "complete"
        and job.structural_audit.get("expected_chunks") == job.expected_chunk_count
        and job.structural_audit.get("completed_chunks") == job.completed_chunk_count
        and (job.promotion_summary.get("readback") or {}).get("verified") is True
        and (job.promotion_summary.get("readback") or {}).get("source_revision") == job.source_revision
        and job.completion_disposition is not None, "terminal_coverage_carrier_source_incomplete")


async def claim_report_slice(
    backend: Any, *, carrier_run_id: str, provider: Any, config: Any, host_client: str,
    project_root: str | Path,
    bookkeeping_only: bool = False,
    exhausted_bookkeeping: bool = False,
) -> dict[str, Any]:
    """Dual-CAS one shared old slice before the first possible native request."""
    from harness_mem.autonomous.worker import autonomous_runtime_fingerprint
    from harness_mem.hook_background import heartbeat_background_worker
    from harness_mem.maintenance_lock import maintenance_is_locked

    carrier = await backend.structured_store.get_dream_run(carrier_run_id)
    _require_origin(carrier is not None, "terminal_report_carrier_missing")
    if exhausted_bookkeeping:
        _require_origin(bookkeeping_only and provider is None, "terminal_report_bookkeeping_cannot_dispatch")
        carrier, _generation, _trigger = await bound_report_child(backend,
            project_name=carrier.project_name, project_root=project_root, config=config, host_client=host_client,
            child_run_id=carrier.id, exhausted_bookkeeping=True)
    else:
        carrier = await _terminal_carrier(backend, project_name=carrier.project_name, project_root=project_root,
            carrier_run_id=carrier.id, provider=provider, config=config, host_client=host_client)
    origin = await backend.structured_store.get_dream_run(carrier.continuation.get(_PIN))
    _require_origin(origin is not None and _original(origin), "terminal_report_origin_invalid")
    manifest = await _validate_manifest(backend, origin, carrier, project_root=project_root)
    _run, generation, trigger = await _bound_source_account(backend, run=origin,
        project_name=carrier.project_name, project_root=str(project_root), config=config, host_client=host_client,
        require_remaining=bool(_remaining(carrier)) and not exhausted_bookkeeping,
        require_exhausted=exhausted_bookkeeping)
    count, maximum, _claims = _shared_bound(origin, needs_slice=not bookkeeping_only)
    canonical = backend.structured_store._canonical
    origin_raw = canonical.get_payload_json("dream_runs", origin.id)
    child_raw = canonical.get_payload_json("dream_runs", carrier.id)
    _require_origin(origin_raw is not None and child_raw is not None,
                    "terminal_report_checkpoint_missing")
    _require_origin(_digest(json.loads(origin_raw)) == _digest(origin.to_dict())
                    and _digest(json.loads(child_raw)) == _digest(carrier.to_dict()),
                    "terminal_report_initial_snapshot_changed")
    expected_origin = hashlib.sha256(origin_raw.encode()).hexdigest()
    expected_child = hashlib.sha256(child_raw.encode()).hexdigest()
    cp = origin.continuation
    takeover = cp.setdefault("terminal_coverage_takeover", {"contract": TERMINAL_TAKEOVER_CONTRACT,
        "slice_count": 0, "claims": {}, "origin_fixed_sha256": _terminal_fixed(origin)})
    ordinal = carrier.continuation.get("slice_count")
    _require_origin(type(ordinal) is int and 0 < ordinal <= manifest["max_slices"], "terminal_report_carrier_slice_invalid")
    key, digest = f"{carrier.id}:{ordinal}", _digest(manifest)
    if bookkeeping_only and not exhausted_bookkeeping:
        _require_origin(not _remaining(carrier) and carrier.continuation.get("completed_signal_indexes")
            == list(range(len(manifest["targets"]))) and any(
                row.get("carrier_run_id") == carrier.id and row.get("kind") == "report_recheck"
                and row.get("manifest_sha256") == digest for row in takeover["claims"].values()),
                "terminal_report_bookkeeping_unproved")
    elif not bookkeeping_only:
        _require_origin(key not in takeover["claims"], "terminal_report_carrier_slice_already_claimed")
    attempts = takeover.setdefault("report_attempts", {})
    existing = attempts.get(digest)
    _require_origin((not bookkeeping_only and existing is None) or (existing is not None and existing.get("carrier_run_id") == carrier.id
        and existing.get("status") in {"claimed", "in_progress", "continuing"}), "terminal_report_contract_already_attempted")
    for old in await backend.structured_store.list_dream_runs(carrier.project_name, limit=200):
        _require_origin(not any(row.get("contract") == CONTRACT
            and (old.id != origin.id or row.get("carrier_run_id") != carrier.id)
            for row in _attempts(old).values()), "terminal_report_account_owner_changed")
    attempt = attempts.setdefault(digest, {"contract": CONTRACT, "manifest_sha256": digest,
        "carrier_run_id": carrier.id, "status": "claimed", "target_bindings": manifest["targets"]})
    code, fixed = autonomous_runtime_fingerprint(), _terminal_fixed(origin)
    claim = {"kind": "report_recheck", "origin_run_id": origin.id, "carrier_run_id": carrier.id,
        "carrier_reflection_id": carrier.reflection_job_id, "manifest_sha256": digest,
        "attempt_id": digest, "runtime_fingerprint": code, "status": "claimed"}
    account_before = None
    if exhausted_bookkeeping:
        from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt
        account_before = _digest(read_task_budget_receipt(Path(backend.data_dir), maintenance_task_scope(trigger, generation)))
        claim = takeover["claims"][key]
    if not bookkeeping_only:
        takeover["claims"][key] = claim
        takeover["slice_count"] = len(takeover["claims"])
    reflection_heartbeat = _carrier_heartbeat(backend, carrier, config=config)
    first_reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    def reflection_identity(row: Any) -> str:
        return _digest({name: row.to_dict().get(name) for name in (
            "id", "project_name", "project_root", "kind", "source", "input_refs", "created_at")})
    reflection_binding = reflection_identity(first_reflection)
    active_reflection_binding = {key: value for key, value in first_reflection.to_dict().items() if key != "updated_at"}
    exhausted_reflection_binding = first_reflection.to_dict() if exhausted_bookkeeping else None

    def heartbeat(*, ledger_only: bool = False) -> None:
        _require_origin(not bookkeeping_only or ledger_only, "terminal_report_bookkeeping_cannot_dispatch")
        owner = backend.reflection_job_store.get(carrier.reflection_job_id)
        _require_origin(owner is not None and owner.status == "processing"
            and {key: value for key, value in owner.to_dict().items() if key != "updated_at"} == active_reflection_binding,
            "terminal_report_reflection_changed")
        _require_origin(not maintenance_is_locked(backend.data_dir, trigger_id=trigger), "exclusive_maintenance_run_active")
        if os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1":
            _require_origin(heartbeat_background_worker(Path(backend.data_dir), project_root=Path(project_root), client=host_client),
                            "background_worker_lease_lost")
        reflection_heartbeat()

    async def persist(current: Any) -> None:
        nonlocal expected_origin, expected_child
        _require_origin(current.id == carrier.id and current.project_name == carrier.project_name,
                        "terminal_report_checkpoint_child_changed")
        _require_origin(_terminal_fixed(origin) == fixed and autonomous_runtime_fingerprint() == code,
                        "terminal_report_history_or_runtime_changed")
        await _validate_manifest(backend, origin, current, project_root=project_root)
        if exhausted_bookkeeping:
            _require_origin(current.status == "failed" and current.resolution_status == "unresolved",
                            "terminal_report_terminal_bookkeeping_invalid")
            await _bound_source_account(backend, run=origin, project_name=carrier.project_name,
                project_root=str(project_root), config=config, host_client=host_client,
                require_remaining=False, require_exhausted=True, generation=generation, trigger_id=trigger)
            _require_origin(_digest(read_task_budget_receipt(Path(backend.data_dir),
                maintenance_task_scope(trigger, generation))) == account_before, "terminal_report_bookkeeping_account_changed")
            _exhausted_owner(backend, origin, carrier, manifest, project_root=project_root)
        owner = backend.reflection_job_store.get(carrier.reflection_job_id)
        _require_origin(owner is not None and reflection_identity(owner) == reflection_binding,
                        "terminal_report_reflection_changed")
        if exhausted_bookkeeping:
            _require_origin(owner.to_dict() == exhausted_reflection_binding, "terminal_report_reflection_changed")
        if current.status in {"processing", "continuing"}:
            heartbeat(ledger_only=True)
        else:
            _require_origin(current.status in {"failed", "completed"}
                and (owner.status in {"processing", "failed", "completed"}
                     or (exhausted_bookkeeping and owner.status == "retryable")),
                            "terminal_report_terminal_bookkeeping_invalid")
        status = current.status
        attempt["status"] = ("in_progress" if status == "processing" else
            "unresolved" if status == "completed" and current.resolution_status != "resolved" else status)
        attempt["remaining_ids"] = sorted(_remaining(current))
        attempt["child_payload_sha256"] = _digest(current.to_dict())
        claim["status"] = attempt["status"]
        origin_payload, child_payload = origin.to_dict(), current.to_dict()
        await asyncio.to_thread(canonical.apply_payload_transaction,
            idempotency_key="terminal-report-checkpoint:" + _digest({"origin_before": expected_origin,
                "child_before": expected_child, "origin": origin_payload, "child": child_payload}),
            mutations=[{"operation": "upsert", "collection": "dream_runs", "entity_id": origin.id,
                "payload": origin_payload, "expected_sha256": expected_origin},
                {"operation": "upsert", "collection": "dream_runs", "entity_id": current.id,
                 "payload": child_payload, "expected_sha256": expected_child}])
        saved_origin = canonical.get_payload_json("dream_runs", origin.id)
        saved_child = canonical.get_payload_json("dream_runs", current.id)
        if (saved_origin is None or saved_child is None
                or _digest(json.loads(saved_origin)) != _digest(origin_payload)
                or _digest(json.loads(saved_child)) != _digest(child_payload)):
            raise CanonicalTransactionPreconditionError("terminal_report_checkpoint_readback_changed")
        expected_origin = hashlib.sha256(saved_origin.encode()).hexdigest()
        expected_child = hashlib.sha256(saved_child.encode()).hexdigest()
        # The canonical transaction is the writer. Refresh only its derived
        # index row, never call save_dream_run and overwrite guarded payloads.
        projection = {name: getattr(current, name) for name in (
            "id", "project_name", "started_at", "completed_at", "status", "trigger_source",
            "reflection_job_id", "policy_version", "duration_ms")}
        index = backend.structured_store._index
        if index.get("dream_runs", current.id) is None:
            await asyncio.to_thread(index.insert, "dream_runs", projection)
        else:
            await asyncio.to_thread(index.update, "dream_runs", current.id, projection)

    if not exhausted_bookkeeping:
        await persist(carrier)
    return {"origin": origin, "carrier": carrier, "manifest": manifest,
            "manifest_sha256": digest, "attempt_id": digest, "heartbeat": heartbeat, "persist": persist,
            "generation": generation, "trigger_id": trigger, "remaining_original_slices": maximum - count - takeover["slice_count"],
            "account_binding_sha256": account_before, "runtime_fingerprint": code}


async def close_exhausted_report_child(backend: Any, *, child_run_id: str, project_name: str,
    project_root: str | Path, config: Any, host_client: str, generation: str, trigger_id: str) -> dict[str, Any]:
    """Close only a proved exhausted task through the existing dual-CAS owner."""
    from harness_mem.hook_background import background_generation_from_env, heartbeat_background_worker
    _require_origin(os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1"
        and background_generation_from_env() == generation, "continuation_detached_owner_required")
    try:
        child, actual_generation, actual_trigger = await bound_report_child(backend,
            project_name=project_name, project_root=project_root, config=config, host_client=host_client,
            child_run_id=child_run_id, exhausted_bookkeeping=True)
    except ValueError as exc:
        if str(exc) == "continuation_budget_not_exhausted":
            return {}
        raise
    _require_origin((generation, trigger_id) == (actual_generation, actual_trigger), "continuation_pointer_mismatch")
    _require_origin(heartbeat_background_worker(Path(backend.data_dir), project_root=Path(project_root), client=host_client),
                    "background_worker_lease_lost")
    context = await claim_report_slice(backend, carrier_run_id=child.id, provider=None,
        config=config, host_client=host_client, project_root=project_root,
        bookkeeping_only=True, exhausted_bookkeeping=True)
    current = context["carrier"].model_copy(deep=True)
    current.status, current.execution_status, current.resolution_status = "failed", "failed", "unresolved"
    current.completed_at = datetime.now(timezone.utc)
    current.continuation = {**current.continuation, "execution_status": "failed", "resolution_status": "unresolved",
        "terminal_report_budget_closure": {"reason": "continuation_budget_exhausted",
            "account_binding_sha256": context["account_binding_sha256"],
            "runtime_fingerprint": context["runtime_fingerprint"],
            "remaining_ids": sorted(_remaining(current))}}
    await context["persist"](current)
    return {"status": "failed", "run_id": current.id, "reason": "continuation_budget_exhausted",
        "execution_status": "failed", "resolution_status": "unresolved",
        "completed_target_count": len(current.continuation["completed_signal_indexes"]),
        "target_count": len(current.continuation["target_ids"]), "remaining_target_ids": sorted(_remaining(current))}
