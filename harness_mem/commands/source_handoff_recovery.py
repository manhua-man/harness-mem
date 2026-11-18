"""Continue exact source-bound handoffs through the common assimilation owner.

The original completed source job and failed Dream remain immutable. A carrier
owns only a new checkpoint and, after verified readback, closes its handoffs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import threading
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt
from harness_mem.autonomous.models import AssimilationDecision, DistillCandidate
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.evidence_admission import _source_report_context
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp.distill_projection import _parse_exchanges, render_distill_exchange_windows

CONTRACT = "explicit-source-handoff-recovery-v1"
_CARRIER_CONTRACT = "source-handoff-carrier-index-v2"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _require(value: Any, reason: str) -> None:
    if not value:
        raise ValueError("source_handoff_" + reason)


def _account(backend: Any, binding: Mapping[str, Any]) -> dict[str, Any]:
    account = read_task_budget_receipt(Path(backend.data_dir), binding["task_scope"])
    _require(isinstance(account, dict) and account.get("task_scope") == binding["task_scope"]
             and account.get("host_client") == binding["host_client"], "account_changed")
    calls = account.get("calls")
    _require(isinstance(calls, list) and bool(calls) and all(
        row.get("status") in {"completed", "failed", "retried", "cancelled"}
        and row.get("usage_exact") is True
        and isinstance(row.get("usage"), dict)
        and all(type(row["usage"].get(key)) in ((int, float) if key == "duration_seconds" else (int,))
            and math.isfinite(row["usage"][key]) and row["usage"][key] >= 0
            for key in ("input_tokens", "output_tokens", "duration_seconds"))
        for row in calls), "usage_unknown_or_active")
    prefix = binding.get("account_prefix_count")
    if prefix is not None:
        _require(len(calls) >= prefix and _digest(calls[:prefix]) == binding["account_prefix_sha256"]
                 and account.get("bounds") == binding["account_bounds"], "account_prefix_changed")
    return account


def _origin_points(origin: Any, job: Any) -> dict[str, dict[str, Any]]:
    """Only actual source outcomes nominate candidates; caller IDs grant nothing."""
    points: dict[str, dict[str, Any]] = {}
    for point in job.promotion_summary.get("points") or []:
        if point.get("disposition") in {"handoff", "defer"}:
            points[point["candidate_id"]] = {"point": point, "mode": "source_job"}
    coverage = (origin.continuation.get("source_inventory_audit") or {}).get("source_coverage") or {}
    for state in coverage.values():
        binding = state.get("binding") or {}
        if (binding.get("source_job_id") != job.id or binding.get("source_id") != job.source_id
                or binding.get("source_revision") != job.source_revision):
            continue
        _require(state.get("binding_sha256") == _digest(binding), "origin_source_binding_changed")
        for point in state.get("candidate_outcomes") or []:
            if point.get("disposition") in {"handoff", "defer"}:
                identity = point.get("candidate_id")
                _require(identity in state.get("candidate_ids", []), "origin_candidate_missing")
                points[identity] = {"point": point, "mode": "inventory_workspace",
                                    "state_sha256": _digest(state)}
    return points


async def _current_identity(backend: Any, project_name: str, project_root: str) -> str:
    from harness_mem.commands.dream_assimilation import _entry_version_snapshot
    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name, project_root=project_root)
    return _digest(sorted((_entry_version_snapshot(entry) for entry in entries), key=lambda row: row["id"]))


async def prepare_source_handoff_recovery(
    backend: Any, *, project_name: str, project_root: str | Path, run_id: str,
    origin_run_id: str, source_job_id: str, handoff_ids: Sequence[str],
) -> dict[str, Any]:
    """Read-only, exact nomination and frozen identities; no extraction or write."""
    root = str(Path(project_root).resolve())
    _require(run_id and origin_run_id and run_id != origin_run_id, "carrier_identity_invalid")
    _require(bool(handoff_ids) and len(handoff_ids) <= 8
             and len(set(handoff_ids)) == len(handoff_ids), "selection_invalid")
    origin = await backend.structured_store.get_dream_run(origin_run_id)
    _require(origin is not None and origin.project_name == project_name and origin.status == "failed"
             and origin.completed_at is not None, "origin_not_terminal")
    scope = origin.continuation.get("maintenance_scope")
    _require(isinstance(scope, dict) and set(scope) == {"dispatch_generation", "trigger_id"}
             and all(isinstance(value, str) and value for value in scope.values()), "maintenance_scope_missing")
    task = maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
    for row in (origin.continuation.get("task_budget"), origin.continuation.get("source_inventory_audit"),
                (origin.continuation.get("explicit_repair_scope") or {}).get("source")):
        if row is not None:
            _require(row.get("task_scope") == task, "origin_account_mismatch")
    job = backend.transcript_store.get_distill_job(source_job_id)
    _require(job is not None and job.status == "completed" and job.project_name == project_name
             and str(Path(job.project_root).resolve()) == root
             and job.completed_chunk_count == job.expected_chunk_count, "source_job_changed")
    revision, rendering, _raw = _source_report_context(backend, project_name=project_name,
        source_id=job.source_id, source_revision=job.source_revision)
    _require(revision.session_id == job.session_id and revision.client == job.client
             and str(Path(revision.project_root).resolve()) == root, "source_scope_changed")
    readback = job.promotion_summary.get("readback") or {}
    _require(readback.get("verified") is True and readback.get("source_revision") == job.source_revision,
             "source_job_receipt_unproved")
    points = _origin_points(origin, job)
    binding = {"contract": CONTRACT, "project_name": project_name, "project_root": root,
        "run_id": run_id, "origin_run_id": origin.id, "origin_sha256": _digest(origin.to_dict()),
        "source_job_id": job.id, "source_job_sha256": _digest(job.to_dict()),
        "source_id": job.source_id, "source_revision": job.source_revision,
        "source_raw_sha256": revision.raw_sha256, "host_client": job.client,
        "maintenance_scope": dict(scope), "task_scope": task,
        "current_identity_sha256": await _current_identity(backend, project_name, root)}
    account = _account(backend, binding)
    binding.update(account_prefix_count=len(account["calls"]),
                   account_prefix_sha256=_digest(account["calls"]), account_bounds=account["bounds"])
    store, canonical = backend.structured_store.knowledge_store, backend.structured_store._canonical
    rows = []
    for identity in handoff_ids:
        handoff = await backend.structured_store.get_task_handoff(identity)
        _require(handoff is not None and handoff.project_name == project_name
                 and handoff.status == "in_progress" and handoff.context.get("distill_job_id") == job.id,
                 "handoff_changed")
        candidate_id = handoff.context.get("candidate_id")
        _require(handoff.task_id == "assimilation:" + str(candidate_id) and candidate_id in points,
                 "handoff_not_original_outcome")
        point = points[candidate_id]
        if point["mode"] == "source_job":
            _require(job.session_id == scope["trigger_id"] and any(
                note in {"Hook session distill succeeded: " + job.id, "Hook session distill verified: " + job.id}
                for note in origin.notes or []), "origin_source_job_unproved")
        _require(point["point"].get("handoff_id") == identity, "handoff_outcome_changed")
        raw = canonical.get_payload_json("task_handoffs", identity)
        _require(raw is not None and _digest(json.loads(raw)) == _digest(handoff.to_dict()),
                 "handoff_canonical_changed")
        candidate = await store.get_candidate(candidate_id)
        evidence = await store.list_evidence(candidate_id)
        row = {"handoff_id": identity, "handoff_sha256": hashlib.sha256(raw.encode()).hexdigest(),
               "original_candidate_id": candidate_id, "original_point_sha256": _digest(point),
               "mode": "retained_workspace" if candidate is not None else "rehydrate_report"}
        if candidate is not None:
            _require(candidate.project_name == project_name and candidate.status in {"deferred", "assimilated"}
                     and len(evidence) == 1 and evidence[0].distill_job_id == job.id
                     and evidence[0].verification_outcome == "verified", "retained_workspace_unproved")
            if candidate.source_report is not None:
                _require(candidate.source_report.model_dump(mode="json") == handoff.context.get("source_report"),
                         "report_account_changed")
            row.update(candidate_sha256=_digest(candidate.to_dict()),
                       evidence_sha256=_digest([value.to_dict() for value in evidence]))
        else:
            _require(not evidence and point["mode"] == "source_job"
                     and point["point"].get("verification_outcome") == "verified"
                     and point["point"].get("answer_status") == "ANSWERED", "cleaned_candidate_unproved")
            report = SourceReport.model_validate(handoff.context.get("source_report"))
            _require(report.source_id == job.source_id and report.source_revision == job.source_revision
                     and report.session_id == job.session_id and report.speaker == "assistant"
                     and handoff.summary == report.render_statement(), "report_account_changed")
            _require(candidate_id in job.output_candidate_ids, "original_ordinal_missing")
            ordinal = job.output_candidate_ids.index(candidate_id) + 1
            expected = str(uuid5(NAMESPACE_URL,
                f"harness-mem:autonomous-knowledge-candidate:{job.id}:{ordinal}:memory:{report.text}"))
            _require(expected == candidate_id, "original_body_identity_changed")
            refs = point["point"].get("verification_refs") or []
            _require(bool(refs) and all(ref.get("kind") == "source_report" and ref.get("role") == report.speaker
                for ref in refs) and sorted({ref.get("exchange_index") for ref in refs}) == report.exchange_indexes,
                "report_refs_changed")
            windows = {window["exchange_index"]: window for window in render_distill_exchange_windows(rendering, report.exchange_indexes)}
            _require(all(ref["content_sha256"] == windows[ref["exchange_index"]]["content_sha256"]
                for ref in refs), "report_source_digest_changed")
            row.update(ordinal=ordinal, report_sha256=_digest(report.model_dump(mode="json")),
                       refs_sha256=_digest(refs))
        rows.append(row)
    binding["source_candidates"] = rows
    return {"contract": CONTRACT, "binding": binding, "binding_sha256": _digest(binding)}


async def enqueue_source_handoff_recovery(
    backend: Any, *, project_name: str, project_root: str | Path, config: Any,
    host_client: str, origin_run_id: str, source_job_id: str, handoff_ids: Sequence[str],
) -> dict[str, Any]:
    """Stage an original native task's finite handoffs on its existing queue.

    This schedules existing obligations. It does not fabricate a host event or
    reopen the original failed run, source job, candidate or task account.
    """
    from harness_mem.commands.dream_continuation import _bound_origin, _bound_source_account
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.hook_background import dispatch_bound_continuation
    from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError

    identity = str(uuid5(NAMESPACE_URL, "harness-mem:source-handoff-carrier:" + _digest({
        "contract": _CARRIER_CONTRACT,
        "project": project_name, "origin": origin_run_id, "job": source_job_id,
        "handoffs": list(handoff_ids)})))
    existing = await backend.structured_store.get_dream_run(identity)
    created_sha = None
    if existing is None:
        latest = await backend.structured_store.list_dream_runs(project_name, limit=1)
        _require(not latest or latest[0].status not in {"processing", "continuing"},
                 "another_carrier_active")
        frozen = await prepare_source_handoff_recovery(backend, project_name=project_name,
            project_root=project_root, run_id=identity, origin_run_id=origin_run_id,
            source_job_id=source_job_id, handoff_ids=handoff_ids)
        binding = frozen["binding"]
        _require(binding["host_client"] == host_client, "carrier_host_changed")
        job = backend.transcript_store.get_distill_job(source_job_id)
        _require(job.session_id == binding["maintenance_scope"]["trigger_id"],
                 "native_task_required")
        existing = DreamRun(id=identity, project_name=project_name, status="continuing",
            execution_status="continuing", resolution_status="unresolved", trigger_source="ide_hook",
            notes=["Hook session distill verified: " + source_job_id], continuation={
                "version": "dream-slices-v3", "maintenance_scope": binding["maintenance_scope"],
                "source_handoff_carrier_contract": _CARRIER_CONTRACT,
                "source_handoff_recovery_scope": frozen, "signals": [], "target_ids": [],
                "completed_signal_indexes": [], "slice_count": 0,
                "max_slices": 1 + 2 * len(binding["source_candidates"])})
        await _bound_source_account(backend, run=existing, project_name=project_name,
            project_root=str(project_root), config=config, host_client=host_client,
            source_job_id=source_job_id)
        await _assert_fixed(backend, binding)
        canonical = backend.structured_store._canonical
        try:
            created = canonical.apply_payload_transaction(idempotency_key="source-handoff-carrier-create:" +
                _digest(existing.to_dict()), mutations=[{
                    "operation": "upsert", "collection": "dream_runs", "entity_id": identity,
                    "project_name": project_name, "payload": existing.to_dict(), "expected_sha256": None}])
            created_sha = next(row["payload_sha256"] for row in created["mutations"]
                if row["collection"] == "dream_runs" and row["entity_id"] == identity)
        except CanonicalTransactionPreconditionError:
            existing = await backend.structured_store.get_dream_run(identity)
            _require(existing is not None, "carrier_create_race")
    else:
        frozen = existing.continuation.get("source_handoff_recovery_scope") or {}
        binding = frozen.get("binding") or {}
        _require(binding.get("origin_run_id") == origin_run_id
            and binding.get("source_job_id") == source_job_id
            and [row["handoff_id"] for row in binding.get("source_candidates") or []] == list(handoff_ids),
            "carrier_selection_changed")
    try:
        # Canonical CAS is the only payload writer. Latest-run discovery reads
        # the separate derived index, so publish only the current projection
        # before asking the existing continuation owner to discover this run.
        await _project_handoff_carrier(backend, identity)
        _run, generation, trigger = await _bound_origin(backend, project_name=project_name,
            project_root=str(project_root), config=config, host_client=host_client, run_id=identity)
        queued = dispatch_bound_continuation(Path(backend.data_dir), project_root=Path(project_root),
            client=host_client, trigger_id=trigger, generation=generation, resume_run_id=identity)
    except Exception:
        if created_sha is not None:
            failed = existing.model_copy(deep=True)
            failed.status, failed.execution_status, failed.resolution_status = "failed", "failed", "unresolved"
            failed.completed_at = datetime.now(timezone.utc)
            failed.notes = [*(failed.notes or []), "source_handoff_carrier_dispatch_failed"]
            try:
                backend.structured_store._canonical.apply_payload_transaction(
                    idempotency_key="source-handoff-carrier-dispatch-failure:" + created_sha, mutations=[{
                        "operation": "upsert", "collection": "dream_runs", "entity_id": identity,
                        "project_name": project_name, "payload": failed.to_dict(), "expected_sha256": created_sha}])
            except CanonicalTransactionPreconditionError:
                pass  # A worker's newer checkpoint is authoritative.
            await _project_handoff_carrier(backend, identity)
        raise
    return {"status": "queued", "run_id": identity, "generation": generation,
            "spawned": queued.spawned, "coalesced": queued.coalesced}


async def _project_handoff_carrier(backend: Any, identity: str) -> None:
    """Refresh discovery metadata without rewriting a guarded canonical run."""
    current = await backend.structured_store.get_dream_run(identity)
    _require(current is not None, "carrier_projection_missing")
    projection = {name: getattr(current, name) for name in (
        "id", "project_name", "started_at", "completed_at", "status", "trigger_source",
        "reflection_job_id", "policy_version", "duration_ms")}
    # Atomic index upsert also handles concurrent callers publishing the same
    # newly created ID. It has no authority over the canonical payload.
    await asyncio.to_thread(backend.structured_store.index.upsert, "dream_runs", projection)


class _RecoveryProvider:
    """The shared worker's source helpers retain this carrier's actual phase."""
    def __init__(self, provider: Any, *, phase: str, prefix: str):
        self._provider, self._phase, self._prefix = provider, phase, prefix

    def __getattr__(self, key: str) -> Any:
        return getattr(self._provider, key)

    def bind_task_budget(self, binding: Any, *, phase: str, slice_id: str,
                         retry_of: str | None = None) -> None:
        self._provider.bind_task_budget(binding, phase=self._phase,
            slice_id=self._prefix + ":" + slice_id, retry_of=retry_of)


def _packet(backend: Any, binding: Mapping[str, Any]) -> dict[str, Any]:
    _revision, rendering, _raw = _source_report_context(backend,
        project_name=binding["project_name"], source_id=binding["source_id"],
        source_revision=binding["source_revision"])
    _header, exchanges, _summary = _parse_exchanges(rendering)
    return {"project_name": binding["project_name"], "source_id": binding["source_id"],
        "source_revision": binding["source_revision"], "distill_job_id": binding["source_job_id"],
        "semantic_decision_exchanges": render_distill_exchange_windows(rendering, list(range(1, len(exchanges) + 1)))}


async def _assert_fixed(backend: Any, binding: Mapping[str, Any], *, handoffs: bool = True) -> None:
    origin = await backend.structured_store.get_dream_run(binding["origin_run_id"])
    job = backend.transcript_store.get_distill_job(binding["source_job_id"])
    _require(origin is not None and _digest(origin.to_dict()) == binding["origin_sha256"], "origin_changed")
    _require(job is not None and _digest(job.to_dict()) == binding["source_job_sha256"], "source_job_changed")
    _account(backend, binding)
    if handoffs:
        for row in binding["source_candidates"]:
            raw = backend.structured_store._canonical.get_payload_json("task_handoffs", row["handoff_id"])
            _require(raw is not None and hashlib.sha256(raw.encode()).hexdigest() == row["handoff_sha256"],
                     "handoff_changed")


async def run_source_handoff_recovery(
    backend: Any, *, project_name: str, project_root: str | Path, run_id: str,
    manifest: dict[str, Any], checkpoint: dict[str, Any], notes: list[str], provider: Any,
    persist: Callable[[], Awaitable[None]], boundary: Callable[[], Awaitable[None]] | None = None,
    owner_heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run one finite handoff group; failed confirmation remains unresolved."""
    binding = manifest.get("binding") or {}
    _require(manifest.get("contract") == CONTRACT and binding.get("contract") == CONTRACT
             and manifest.get("binding_sha256") == _digest(binding)
             and binding.get("run_id") == run_id and binding.get("project_name") == project_name
             and binding.get("project_root") == str(Path(project_root).resolve()), "manifest_changed")
    owner = getattr(provider, "task_budget_binding", None)
    _require(owner is not None and owner.task_scope == binding["task_scope"]
             and owner.host_client == binding["host_client"]
             and Path(owner.data_dir).resolve() == Path(backend.data_dir).resolve(), "provider_account_changed")
    saved = {name: getattr(provider, name, None) for name in (
        "_budget_phase", "_budget_slice", "_budget_retry_of", "_last_budget_call_id")}
    _require(saved["_budget_phase"] == "dream", "provider_phase_changed")
    state = checkpoint.setdefault("source_handoff_recovery", {
        "contract": CONTRACT, "binding_sha256": manifest["binding_sha256"],
        "binding": binding,
        "source_job_id": binding["source_job_id"], "status": "prepared", "source_candidates": [],
        "canonical_outcomes": [], "commit_bindings": []})
    _require(state.get("contract") == CONTRACT and state.get("binding_sha256") == manifest["binding_sha256"],
             "checkpoint_changed")
    _require(state.get("binding") == binding, "checkpoint_binding_changed")
    if state["status"] in {"applied", "no_write", "unresolved", "failed"}:
        await _assert_fixed(backend, binding, handoffs=False)
        return {"worked": False, "pending": False, **state}
    await _assert_fixed(backend, binding)
    if not state["source_candidates"]:
        _require(await _current_identity(backend, project_name, binding["project_root"])
                 == binding["current_identity_sha256"], "current_inventory_changed")
    await persist()
    if boundary is not None:
        await boundary()
    loop, cancelled = asyncio.get_running_loop(), threading.Event()

    def heartbeat() -> None:
        if cancelled.is_set():
            raise ProviderError("source handoff recovery cancelled", kind="transient")
        keep_alive = owner_heartbeat or getattr(provider, "_dream_owner_heartbeat", None)
        if keep_alive is not None:
            keep_alive()

    def save(update: dict[str, Any]) -> None:
        async def commit() -> None:
            receipt = update.pop("_receipt", None)
            if receipt is not None:
                notes.append("source handoff recovery receipt: " + json.dumps(receipt, sort_keys=True))
            state.update(update)
            await persist()
            if update.get("status") in {"preparing_candidates", "candidates_ready"} and boundary is not None:
                await boundary()
        asyncio.run_coroutine_threadsafe(commit(), loop).result()

    wrapped = _RecoveryProvider(provider, phase=saved["_budget_phase"],
        prefix=f"source-handoff:{run_id}:{manifest['binding_sha256']}")
    task = asyncio.create_task(asyncio.to_thread(_run_attempt, backend, binding=binding,
        state=state, provider=wrapped, heartbeat=heartbeat, save=save))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=45)
        except Exception:
            pass
        raise
    except Exception as exc:
        from harness_mem.commands.dream import _DreamSliceYield
        if isinstance(exc, _DreamSliceYield):
            raise
        state["status"] = "failed"
        await persist()
        raise
    finally:
        adapters = {"input_capability": getattr(provider, "_input_capability", None),
                    "output_limit_surface": getattr(provider, "_output_surface", None),
                    "explicit_fake_transport": getattr(provider, "_explicit_fake_transport", None)}
        provider.bind_task_budget(owner, phase=saved["_budget_phase"], slice_id=saved["_budget_slice"],
            retry_of=saved["_budget_retry_of"], **adapters)
        provider._last_budget_call_id = saved["_last_budget_call_id"]
    return {"worked": True, "pending": state["status"] not in {"applied", "no_write", "unresolved", "failed"}, **state}


def _run_attempt(backend: Any, *, binding: dict[str, Any], state: dict[str, Any],
                 provider: Any, heartbeat: Callable[[], None], save: Callable[[dict[str, Any]], None]) -> None:
    from harness_mem.autonomous.worker import (
        _assimilate_prepared_in_bounded_batches, _build_candidate_verification_manifest,
        _verify_candidates, _verify_final_knowledge_scope,
    )
    from harness_mem.commands.separated_assimilation import (
        admit_separated_candidate, create_separated_candidates, prepare_separated_assimilation,
        validate_separated_assimilation_decision, apply_separated_assimilation,
    )
    root, project = Path(binding["project_root"]), binding["project_name"]
    runtime = Path(backend.data_dir) / "autonomous" / "provider-runtime"
    store = backend.structured_store.knowledge_store
    packet = _packet(backend, binding)

    def receipt(phase: str, result: Any) -> None:
        if result is not None:
            save({"_receipt": {"contract": CONTRACT, "source_job_id": binding["source_job_id"],
                "phase": phase, **result.receipt()}})

    candidates = list(state["source_candidates"])
    _require(len(candidates) <= len(binding["source_candidates"]) and all(
        candidate["original_candidate_id"] == original["original_candidate_id"]
        for candidate, original in zip(candidates, binding["source_candidates"])), "candidate_mapping_changed")
    if len(candidates) < len(binding["source_candidates"]):
        for index, row in enumerate(binding["source_candidates"]):
            if index < len(candidates):
                continue
            heartbeat()
            asyncio.run(_assert_fixed(backend, binding))
            if row["mode"] == "retained_workspace":
                candidate = asyncio.run(store.get_candidate(row["original_candidate_id"]))
                evidence = asyncio.run(store.list_evidence(row["original_candidate_id"]))
                _require(candidate is not None and _digest(candidate.to_dict()) == row["candidate_sha256"]
                    and _digest([value.to_dict() for value in evidence]) == row["evidence_sha256"],
                    "retained_workspace_changed")
                identity = str(uuid5(NAMESPACE_URL, f"harness-mem:source-handoff-recovery:{_digest(binding)}:{candidate.id}"))
                asyncio.run(admit_separated_candidate(backend, candidate_id=identity,
                    project_name=project, candidate_type=candidate.candidate_type, statement=candidate.statement,
                    distill_job_id=binding["source_job_id"], evidence_basis=evidence[0].evidence_basis,
                    verification_outcome=evidence[0].verification_outcome,
                    verification_refs=evidence[0].verification_refs,
                    verification_reason_codes=evidence[0].verification_reason_codes))
            else:
                handoff = asyncio.run(backend.structured_store.get_task_handoff(row["handoff_id"]))
                report = SourceReport.model_validate(handoff.context["source_report"])
                job = backend.transcript_store.get_distill_job(binding["source_job_id"])
                point = next(point for point in job.promotion_summary["points"]
                             if point["candidate_id"] == row["original_candidate_id"])
                refs = [{key: value for key, value in ref.items() if key not in {"locator_sha256", "bindings"}}
                        for ref in point["verification_refs"]]
                proxy = DistillCandidate(kind="memory", category="knowledge", content=report.text,
                    evidence_basis="source_report", verification_refs=refs)
                arguments = {"kind": "memory", "content": report.text, "evidence_basis": "source_report",
                    "verification_outcome": "unverified", "verification_refs": refs,
                    "verification_reason_codes": []}
                original = _build_candidate_verification_manifest(packet=packet,
                    validated_candidates=[(proxy, arguments)], project_root=root,
                    backend=backend, distill_job_id=job.id)
                result, verified = _verify_candidates(provider, manifest=original,
                    validated_candidates=[(proxy, arguments)], runtime_dir=runtime, heartbeat=heartbeat)
                receipt("candidate_verify", result)
                asyncio.run(_assert_fixed(backend, binding))
                identities = asyncio.run(create_separated_candidates(backend, project_name=project,
                    distill_job_id=job.id, candidate_arguments=[verified[0][1]],
                    _attempt_namespace=f"source-handoff:{_digest(binding)}:{index}", _retire_prior_pending=False))
                identity = identities[0]
                fresh = asyncio.run(store.get_candidate(identity))
                fresh_evidence = asyncio.run(store.list_evidence(identity))
                _require(fresh is not None and fresh.statement == report.text and len(fresh_evidence) == 1,
                         "rehydrated_report_changed")
                if fresh_evidence[0].verification_outcome == "verified":
                    _require(fresh.source_report is not None and fresh.source_report.model_dump(mode="json")
                        == report.model_dump(mode="json"), "rehydrated_report_changed")
                else:
                    # Failed fresh support grants no report-writing authority.
                    # Keep its real result for normal defer/no-write handling.
                    _require(fresh.source_report is None, "unverified_report_authority")
            writing = asyncio.run(store.get_candidate(identity))
            writing_evidence = asyncio.run(store.list_evidence(identity))
            candidates.append({**row, "candidate_id": identity,
                "writing_candidate_sha256": _digest(writing.to_dict()),
                "writing_evidence_sha256": _digest([value.to_dict() for value in writing_evidence])})
            save({"source_candidates": list(candidates), "status": "preparing_candidates"})
        save({"status": "candidates_ready"})
    identities = [row["candidate_id"] for row in candidates]
    if state.get("status") == "committing":
        _finish(backend, binding=binding, state=state, save=save)
        return
    prepared = asyncio.run(prepare_separated_assimilation(backend, project_name=project,
        project_root=str(root), candidate_ids=identities, complete_target_discovery=True))
    # Complete comparison does not enlarge the original inventory audit's
    # empty write-target set. Natural reports may only nominate the same
    # original account; topic/final-source judgment remains the common owner's.
    inventory_mode = any(row["mode"] == "retained_workspace" for row in binding["source_candidates"])
    allowed = set()
    if not inventory_mode:
        reports = [asyncio.run(store.get_candidate(identity)).source_report for identity in identities]
        for identity in prepared.truth_by_handle.values():
            entry = asyncio.run(store.get_entry(identity, project_name=project))
            if entry is not None and entry.source_report is not None and any(
                report is not None and report.same_account_source(entry.source_report) for report in reports):
                allowed.add(identity)
    comparison = [{"id": prepared.truth_by_handle[row["handle"]],
                   **{key: value for key, value in row.items() if key != "handle"}, "comparison_only": True}
                  for row in prepared.manifest.get("current_truth") or []]
    context = {"kind": "runtime_maintenance_scope_not_source_evidence", "content": json.dumps({
        "contract": CONTRACT, "comparison_current_truth": comparison,
        "instruction": "All supplied current rows are comparisons, not source evidence. Discovery completeness is not absence. "
            "Only supplied writable handles authorize a target. Preserve every applicable qualifier and report account. "
            "Choose a genuinely missing add or justified no_write/defer/handoff when no writable target exists."},
        ensure_ascii=False, sort_keys=True)}
    prepared = replace(prepared,
        truth_by_handle={key: value for key, value in prepared.truth_by_handle.items() if value in allowed},
        manifest={**prepared.manifest, "current_truth": [row for row in prepared.manifest.get("current_truth") or []
            if prepared.truth_by_handle[row["handle"]] in allowed],
            "session_context": [context, *(prepared.manifest.get("session_context") or [])]})
    # The inventory is complete; it is not an absence verdict or permission to
    # add a duplicate, cross accounts, drop qualifiers, or force a disposition.
    validated = []
    for identity in identities:
        candidate = asyncio.run(store.get_candidate(identity))
        evidence = asyncio.run(store.list_evidence(identity))
        _require(candidate is not None and len(evidence) == 1
            and evidence[0].distill_job_id == binding["source_job_id"], "workspace_missing")
        refs = [ref.model_dump(mode="json", exclude={"locator_sha256", "bindings"})
                for ref in evidence[0].verification_refs]
        proxy = DistillCandidate(kind=candidate.candidate_type, content=candidate.statement,
            evidence_basis=evidence[0].evidence_basis, verification_refs=refs)
        # The verifier projection carries the exact already-rendered statement.
        # Its kind stays the original candidate kind; no trigger/pattern or
        # relation fields are guessed from a serialized statement.
        validated.append((proxy, {"kind": "memory", "content": candidate.statement}))
    original = _build_candidate_verification_manifest(packet=packet, validated_candidates=validated,
        project_root=root, backend=backend, distill_job_id=binding["source_job_id"])
    if prepared.eligible_candidate_ids:
        result = _assimilate_prepared_in_bounded_batches(provider, prepared=prepared,
            runtime_dir=runtime, heartbeat=heartbeat)
        receipt("assimilate", result)
        plan = validate_separated_assimilation_decision(prepared, result.decision)
    else:
        plan = validate_separated_assimilation_decision(prepared, AssimilationDecision(points=[]))
    _require(all(set(point.get("matched_truth_ids") or []).issubset(allowed) for point in plan["points"]),
             "target_scope_expanded")
    final, plan = _verify_final_knowledge_scope(provider, backend=backend, prepared=prepared,
        plan=plan, original_manifest=original, governed_candidate_ids=identities,
        runtime_dir=runtime, heartbeat=heartbeat)
    receipt("final_scope", final)
    judgments = plan.pop("_supplied_final_judgments", {})
    for point in plan["points"]:
        if point["candidate_id"] in judgments:
            point["final_scope_judgment"] = judgments[point["candidate_id"]]
    asyncio.run(_assert_fixed(backend, binding))
    # Store the exact verified plan in the existing finite workspace, never in
    # Dream's content-free checkpoint. This permits commit crash recovery.
    plan_path = runtime / ("source-handoff-plan-" + _digest(binding) + ".json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_bytes = json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()
    plan_path.write_bytes(plan_bytes)
    commits = _planned_commits(backend, plan)
    save({"status": "committing", "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
          "plan_path": str(plan_path), "canonical_outcomes": [], "commit_bindings": commits})
    heartbeat()
    outcome = asyncio.run(apply_separated_assimilation(backend, project_name=project,
        project_root=str(root), candidate_ids=identities, plan=plan))
    save({"result_sha256": _digest(outcome), "apply_outcomes": [
        {key: point.get(key) for key in ("candidate_id", "disposition", "canonical_truth_ids", "handoff_id")}
        for point in outcome["points"]]})
    _finish(backend, binding=binding, state=state, save=save)


def _item_snapshot(item: Mapping[str, Any]) -> dict[str, Any]:
    report = item.get("source_report")
    if isinstance(report, SourceReport):
        report = report.model_dump(mode="json")
    return {"title": item["title"], "statement": item["statement"],
            "topic_path": item["topic_path"], "source_report": report}


def _planned_commits(backend: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    from harness_mem.commands.knowledge_assimilation import (
        _candidate_knowledge_items, _knowledge_item_id, assimilation_decision_id,
    )
    commits = []
    for point in plan["points"]:
        if point["disposition"] not in {"add", "replace", "refine"}:
            continue
        candidate = asyncio.run(backend.structured_store.knowledge_store.get_candidate(point["candidate_id"]))
        items = _candidate_knowledge_items(candidate, point, predecessor=candidate.source_report)
        truth = [_knowledge_item_id(candidate.project_name, item) for item in items]
        decision = assimilation_decision_id(candidate_id=candidate.id, disposition=point["disposition"],
            knowledge_ids=truth, predecessor_ids=point.get("matched_truth_ids") or [], reason=point["reason"])
        commits.append({"candidate_id": candidate.id, "decision_id": decision, "status": "committing",
            "point_sha256": _digest(point), "truth_ids": truth,
            "truth_semantic_sha256": [_digest(_item_snapshot(item)) for item in items]})
    return commits


def _finish(backend: Any, *, binding: dict[str, Any], state: dict[str, Any],
            save: Callable[[dict[str, Any]], None]) -> None:
    """Read back the normal owner's actual decisions before handoff closure."""
    from harness_mem.commands.knowledge_assimilation import _verify_normal_search_after_truth_write
    store, canonical = backend.structured_store.knowledge_store, backend.structured_store._canonical
    path = Path(state["plan_path"])
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == state["plan_sha256"], "verified_plan_changed")
    plan = json.loads(raw)
    outcomes, commits, unresolved, promoted = [], [], False, False
    planned_commits = list(state["commit_bindings"])
    for row in state["source_candidates"]:
        candidate = asyncio.run(store.get_candidate(row["candidate_id"]))
        points = [point for point in plan["points"] if point["candidate_id"] == row["candidate_id"]]
        _require(candidate is not None and bool(points), "terminal_workspace_missing")
        original_handoff = next(value for value in binding["source_candidates"]
                                if value["handoff_id"] == row["handoff_id"])
        resolved, point_proofs = True, []
        for point in points:
            disposition = point["disposition"]
            resolved = resolved and disposition in {"add", "replace", "refine", "confirm", "no_write"}
            truth = list(point.get("matched_truth_ids") or []) if disposition == "confirm" else []
            if disposition in {"add", "replace", "refine"}:
                found = [value for value in planned_commits if value["candidate_id"] == candidate.id
                         and value["point_sha256"] == _digest(point)]
                _require(len(found) == 1, "commit_decision_unproved")
                proof = found[0]
                truth, decision = list(proof["truth_ids"]), proof["decision_id"]
                transaction = canonical.payload_transaction_result("knowledge-change:" + decision)
                _require(transaction is not None and asyncio.run(store.current_change_committed(decision)),
                         "commit_missing")
                entries = [asyncio.run(store.get_entry(identity, project_name=binding["project_name"],
                    project_root=binding["project_root"])) for identity in truth]
                _require(all(entry is not None for entry in entries) and bool(entries), "commit_readback_missing")
                _require([_digest(_item_snapshot({"title": entry.title, "statement": entry.statement,
                    "topic_path": entry.module_path, "source_report": entry.source_report})) for entry in entries]
                    == proof["truth_semantic_sha256"], "commit_readback_changed")
                for identity in point.get("matched_truth_ids") or []:
                    _require(asyncio.run(store.get_entry(identity, project_name=binding["project_name"])) is None,
                             "predecessor_still_current")
                asyncio.run(_verify_normal_search_after_truth_write(backend, project_name=binding["project_name"],
                    project_root=Path(binding["project_root"]), added_entries=entries, predecessor_entries=[]))
                source_proofs = []
                truth_bindings = []
                mutations = {(value.get("collection"), value.get("entity_id")): value
                             for value in transaction.get("mutations") or []}
                for entry in entries:
                    entry_raw = canonical.get_payload_json("knowledge_entries", entry.id)
                    write = mutations.get(("knowledge_entries", entry.id)) or {}
                    _require(entry_raw is not None and write.get("operation") == "upsert"
                        and write.get("payload_sha256") == hashlib.sha256(entry_raw.encode()).hexdigest(),
                        "commit_payload_changed")
                    sources = asyncio.run(store.list_sources(entry.id))
                    _require(bool(sources), "commit_sources_missing")
                    for source in sources:
                        source_raw = canonical.get_payload_json("knowledge_sources", source.id)
                        source_write = mutations.get(("knowledge_sources", source.id)) or {}
                        _require(source_raw is not None and source_write.get("operation") == "upsert"
                            and source_write.get("payload_sha256") == hashlib.sha256(source_raw.encode()).hexdigest(),
                            "commit_sources_changed")
                        source_proofs.append({"source_id": source.id, "knowledge_id": entry.id,
                                             "payload_sha256": hashlib.sha256(source_raw.encode()).hexdigest()})
                    truth_bindings.append({"id": entry.id,
                        "payload_sha256": hashlib.sha256(entry_raw.encode()).hexdigest(),
                        "scope_sha256": _digest(_item_snapshot({"title": entry.title,
                            "statement": entry.statement, "topic_path": entry.module_path,
                            "source_report": entry.source_report})),
                        "sources": [value for value in source_proofs if value["knowledge_id"] == entry.id]})
                commits.append({**proof, "original_candidate_id": row["original_candidate_id"],
                    "status": "applied", "sources": source_proofs, "truth_bindings": truth_bindings,
                    "transaction_sha256": _digest(transaction),
                    "truth_payload_sha256": [_digest(entry.to_dict()) for entry in entries]})
                promoted = True
            elif disposition in {"confirm", "no_write"}:
                applied = [value for value in state.get("apply_outcomes") or []
                    if value["candidate_id"] == candidate.id and value["disposition"] == disposition]
                _require(candidate.status == "assimilated" and len(applied) == 1,
                         "terminal_decision_unproved")
                if disposition == "confirm":
                    entries = [asyncio.run(store.get_entry(identity, project_name=binding["project_name"]))
                               for identity in truth]
                    _require(bool(entries) and all(entries), "confirmed_target_missing")
                    asyncio.run(_verify_normal_search_after_truth_write(backend, project_name=binding["project_name"],
                        project_root=Path(binding["project_root"]), added_entries=entries, predecessor_entries=[]))
            else:
                resolved = False
            point_proofs.append({"disposition": disposition, "point_sha256": _digest(point), "truth_ids": truth,
                "truth_bindings": commits[-1]["truth_bindings"] if disposition in {"add", "replace", "refine"} else []})
        if resolved:
            _close_handoff(backend, binding=binding, row=original_handoff, proofs=point_proofs)
        else:
            unresolved = True
        outcomes.append({**row, "status": "resolved" if resolved else "unresolved",
                         "point_proofs": point_proofs, "candidate_sha256": _digest(candidate.to_dict()),
                         "terminal_evidence_sha256": _digest([value.to_dict() for value in
                             asyncio.run(store.list_evidence(candidate.id))])})
        # Keep proved earlier writes even if a later point fails its readback.
        pending_commits = [value for value in planned_commits
                           if not any(value["decision_id"] == done["decision_id"] for done in commits)]
        save({"canonical_outcomes": list(outcomes), "commit_bindings": [*commits, *pending_commits]})
    save({"status": "unresolved" if unresolved else "applied" if promoted else "no_write",
          "canonical_outcomes": outcomes, "commit_bindings": commits})


def _close_handoff(backend: Any, *, binding: dict[str, Any], row: dict[str, Any],
                    proofs: list[dict[str, Any]]) -> None:
    canonical = backend.structured_store._canonical
    raw = canonical.get_payload_json("task_handoffs", row["handoff_id"])
    _require(raw is not None, "handoff_missing_at_close")
    payload = json.loads(raw)
    witness = {"contract": CONTRACT, "binding_sha256": _digest(binding), "run_id": binding["run_id"],
        "source_job_id": binding["source_job_id"], "original_candidate_id": row["original_candidate_id"],
        "points_sha256": _digest(proofs)}
    if payload.get("status") == "done":
        _require(payload.get("context", {}).get("source_handoff_resolution") == witness, "handoff_close_changed")
        return
    _require(hashlib.sha256(raw.encode()).hexdigest() == row["handoff_sha256"], "handoff_close_changed")
    payload["status"] = "done"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["context"] = {**payload["context"], "source_handoff_resolution": witness}
    mutations = [{
        "operation": "upsert", "collection": "task_handoffs", "entity_id": row["handoff_id"],
        "payload": payload, "expected_sha256": row["handoff_sha256"]}]
    for point in proofs:
        for truth in point.get("truth_bindings") or []:
            mutations.append({"operation": "assert", "collection": "knowledge_entries", "entity_id": truth["id"],
                "project_name": binding["project_name"], "expected_sha256": truth["payload_sha256"]})
            mutations.extend({"operation": "assert", "collection": "knowledge_sources", "entity_id": source["source_id"],
                "project_name": binding["project_name"], "expected_sha256": source["payload_sha256"]}
                for source in truth["sources"])
    canonical.apply_payload_transaction(idempotency_key="source-handoff-close:" + _digest(witness), mutations=mutations)
    _require(_digest(canonical.get_payload("task_handoffs", row["handoff_id"])) == _digest(payload),
             "handoff_close_readback_changed")


async def read_source_handoff_recovery_proof(
    backend: Any, *, run_id: str, origin_run_id: str, source_job_id: str,
) -> dict[str, Any]:
    """Independent read-only proof for subsequent source-inventory auditing.

    Resolved points can be consumed even when another point remains deferred.
    This never changes the historical failed leaf or infers missing coverage.
    """
    carrier = await backend.structured_store.get_dream_run(run_id)
    _require(carrier is not None and carrier.status in {"completed", "failed"}
             and carrier.completed_at is not None, "proof_carrier_not_terminal")
    state = carrier.continuation.get("source_handoff_recovery") or {}
    binding = state.get("binding") or {}
    _require(state.get("contract") == CONTRACT and state.get("binding_sha256") == _digest(binding)
             and binding.get("run_id") == run_id and binding.get("origin_run_id") == origin_run_id
             and binding.get("source_job_id") == source_job_id, "proof_binding_changed")
    await _assert_fixed(backend, binding, handoffs=False)
    await asyncio.to_thread(_packet, backend, binding)
    store, canonical = backend.structured_store.knowledge_store, backend.structured_store._canonical
    proven = []
    for outcome in state.get("canonical_outcomes") or []:
        if outcome.get("status") != "resolved":
            continue
        original = next((row for row in binding["source_candidates"]
                         if row["original_candidate_id"] == outcome["original_candidate_id"]), None)
        _require(original is not None, "proof_original_missing")
        if original["mode"] == "retained_workspace":
            old = await store.get_candidate(original["original_candidate_id"])
            evidence = await store.list_evidence(original["original_candidate_id"])
            _require(old is not None and _digest(old.to_dict()) == original["candidate_sha256"]
                and _digest([value.to_dict() for value in evidence]) == original["evidence_sha256"],
                "proof_original_workspace_changed")
        writing = await store.get_candidate(outcome["candidate_id"])
        evidence = await store.list_evidence(outcome["candidate_id"])
        _require(writing is not None and _digest(writing.to_dict()) == outcome["candidate_sha256"]
            and _digest([value.to_dict() for value in evidence]) == outcome["terminal_evidence_sha256"]
            and len(evidence) == 1 and evidence[0].distill_job_id == source_job_id,
            "proof_writing_workspace_changed")
        handoff = await backend.structured_store.get_task_handoff(outcome["handoff_id"])
        witness = {"contract": CONTRACT, "binding_sha256": _digest(binding), "run_id": run_id,
            "source_job_id": source_job_id, "original_candidate_id": outcome["original_candidate_id"],
            "points_sha256": _digest(outcome["point_proofs"])}
        _require(handoff is not None and handoff.status == "done"
            and handoff.context.get("source_handoff_resolution") == witness, "proof_handoff_changed")
        commits = [row for row in state.get("commit_bindings") or []
                   if row["candidate_id"] == writing.id and row.get("status") == "applied"]
        for commit in commits:
            transaction = canonical.payload_transaction_result("knowledge-change:" + commit["decision_id"])
            _require(transaction is not None and _digest(transaction) == commit["transaction_sha256"],
                     "proof_commit_changed")
            for truth in commit["truth_bindings"]:
                raw = canonical.get_payload_json("knowledge_entries", truth["id"])
                _require(raw is not None and hashlib.sha256(raw.encode()).hexdigest() == truth["payload_sha256"],
                         "proof_truth_changed")
                sources = await store.list_sources(truth["id"])
                _require({value.id for value in sources} == {value["source_id"] for value in truth["sources"]},
                         "proof_sources_changed")
                for source in truth["sources"]:
                    raw = canonical.get_payload_json("knowledge_sources", source["source_id"])
                    _require(raw is not None and hashlib.sha256(raw.encode()).hexdigest() == source["payload_sha256"],
                             "proof_sources_changed")
        proven.append({"original_candidate_id": outcome["original_candidate_id"], "writing_candidate_id": writing.id,
            "original_binding": original, "writing_candidate_sha256": outcome["candidate_sha256"],
            "writing_evidence_sha256": outcome["terminal_evidence_sha256"], "handoff_id": handoff.id,
            "point_proofs": outcome["point_proofs"], "commit_bindings": commits})
    raw = canonical.get_payload_json("dream_runs", run_id)
    _require(raw is not None and _digest(json.loads(raw)) == _digest(carrier.to_dict()), "proof_carrier_changed")
    return {"contract": CONTRACT, "recovery_run_id": run_id, "origin_run_id": origin_run_id,
        "source_job_id": source_job_id, "source_id": binding["source_id"], "source_revision": binding["source_revision"],
        "binding_sha256": state["binding_sha256"], "task_scope": binding["task_scope"],
        "payload_sha256": hashlib.sha256(raw.encode()).hexdigest(), "resolved": proven}
