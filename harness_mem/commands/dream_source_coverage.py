"""Bounded retained-source coverage work belonging to one existing Dream run.

This is not another source intake or a history replay. Only current successors
of an applied replacement in this run can offer their original user source to
the normal extraction/admission owner. The continuation stores no source prose.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.evidence_admission import (
    _reopen_complete_user_context,
    _source_report_context,
)
from harness_mem.commands.dream_assimilation import _entry_version_snapshot
from harness_mem.mcp.distill_projection import _parse_exchanges, render_distill_exchange_windows
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


CONTRACT = "dream-applied-source-coverage-v5"
_PREVIOUS_CONTRACT = "dream-applied-source-coverage-v1"
_INTERRUPTED_CONTRACT = "dream-applied-source-coverage-v2"
_PARTIAL_CONTRACT = "dream-applied-source-coverage-v3"
_ZERO_CONTRACT = "dream-applied-source-coverage-v4"
TERMINAL_TAKEOVER_CONTRACT = "terminal-source-coverage-v1"
_TERMINAL = frozenset({"applied", "no_write", "unresolved", "failed", "not_applicable"})


def _contract_retryable(state: Mapping[str, Any]) -> bool:
    """Only a proved semantic no-write can cross this specific contract change."""
    binding = state.get("binding") or {}
    if (binding.get("contract") != _PREVIOUS_CONTRACT
            or state.get("status") not in {"no_write", "unresolved"}
            or state.get("reason_code") not in {
                "source_coverage_no_candidate", "source_coverage_no_new_claim",
                "source_coverage_partial_resolution"}
            or state.get("commit_bindings") or state.get("committed_candidate_ids")
            or any(row.get("truth_ids") and row.get("disposition") != "confirm"
                   for row in state.get("candidate_outcomes") or [])
            or any((state.get("result_status_counts") or {}).get(key)
                   for key in ("promoted", "applied"))):
        return False
    return state.get("binding_sha256") == _digest(binding)


def _coverage_pending(state: Mapping[str, Any] | None) -> bool:
    """One eligibility rule for traversal, typed wake selection and its bound."""
    return (not state or state.get("status") not in _TERMINAL or _contract_retryable(state)
            or _partial_retryable(state) or _zero_retryable(state))


def _zero_retryable(state: Mapping[str, Any]) -> bool:
    """Nominate only the preceding contract's exact unverified-zero outcome."""
    binding = state.get("binding") or {}
    return (binding.get("contract") == _ZERO_CONTRACT and state.get("status") == "no_write"
        and state.get("reason_code") == "source_coverage_no_candidate"
        and state.get("binding_sha256") == _digest(binding)
        and state.get("candidate_ids") == [] and state.get("commit_bindings") == []
        and not state.get("committed_candidate_ids") and not state.get("candidate_outcomes")
        and not any((state.get("result_status_counts") or {}).values())
        and not any((state.get("point_disposition_counts") or {}).values())
        and not any((state.get("candidate_status_counts") or {}).values()))


def _interrupted_retryable(state: Mapping[str, Any]) -> bool:
    """Nominate one old interrupted contract; this is never adoption authority."""
    binding = state.get("binding") or {}
    identities = state.get("candidate_ids")
    return (binding.get("contract") == _INTERRUPTED_CONTRACT
        and state.get("status") == "candidates_verified"
        and isinstance(identities, list) and bool(identities)
        and all(isinstance(value, str) and value for value in identities)
        and len(set(identities)) == len(identities)
        and state.get("binding_sha256") == _digest(binding)
        and not state.get("commit_bindings") and not state.get("committed_candidate_ids")
        and not state.get("candidate_outcomes")
        and not any((state.get("result_status_counts") or {}).get(key) for key in ("promoted", "applied")))


def _partial_retryable(state: Mapping[str, Any]) -> bool:
    """Nominate the old partial-add contract, never arbitrary semantic failures."""
    binding, commits = state.get("binding") or {}, state.get("commit_bindings") or []
    outcomes, identities = state.get("candidate_outcomes") or [], state.get("candidate_ids") or []
    return (binding.get("contract") == _PARTIAL_CONTRACT and state.get("status") == "unresolved"
        and state.get("reason_code") == "source_coverage_partial_resolution"
        and state.get("binding_sha256") == _digest(binding) and bool(commits) and bool(identities)
        and len(set(identities)) == len(identities) and len(outcomes) == len(identities)
        and {row.get("candidate_id") for row in outcomes} == set(identities)
        and all(row.get("status") == "applied" and not row.get("predecessor_ids") for row in commits)
        and any(row.get("disposition") in {"defer", "handoff"} for row in outcomes)
        and all((row.get("disposition") == "add" and row.get("status") == "assimilated" and row.get("truth_ids"))
            or (row.get("disposition") in {"defer", "handoff"} and row.get("status") in {"deferred", "assimilated"}
                and not row.get("truth_ids")) for row in outcomes))


def _state_for_binding(state: dict[str, Any] | None, binding: dict[str, Any], *,
                       interrupted_proof: dict[str, Any] | None = None,
                       partial_proof: dict[str, Any] | None = None,
                       zero_proof: dict[str, Any] | None = None) -> dict[str, Any]:
    binding_hash = _digest(binding)
    interrupted = state is not None and _interrupted_retryable(state)
    partial = state is not None and _partial_retryable(state)
    zero = state is not None and _zero_retryable(state)
    if interrupted:
        if (not interrupted_proof or interrupted_proof.get("state_sha256") != _digest(state)
                or interrupted_proof.get("binding_sha256") != binding_hash):
            raise ValueError("source_coverage_interrupted_preflight_required")
    if partial and (not partial_proof or partial_proof.get("state_sha256") != _digest(state)
            or partial_proof.get("binding_sha256") != binding_hash):
        raise ValueError("source_coverage_partial_preflight_required")
    if zero and (not zero_proof or zero_proof.get("state_sha256") != _digest(state)
            or zero_proof.get("binding_sha256") != binding_hash):
        raise ValueError("source_coverage_zero_preflight_required")
    if state is not None and (_contract_retryable(state) or interrupted or partial or zero):
        old_binding = dict(state["binding"])
        old_binding["contract"] = CONTRACT
        if old_binding != binding:
            raise ValueError("source_coverage_attempt_binding_changed")
        # Preserve content-free prior results. Candidate/TaskHandoff owners and
        # terminal takeover claims remain untouched; the new hash namespaces
        # new candidates without reopening the earlier candidate workspace.
        prior = {key: state[key] for key in (
            "status", "reason_code", "binding_sha256", "candidate_ids",
            "result_sha256", "decision_sha256", "result_status_counts", "point_disposition_counts", "candidate_status_counts",
            "terminal_takeover_contract", "commit_bindings", "committed_candidate_ids") if key in state}
        prior["candidate_outcomes"] = [{key: row[key] for key in (
            "candidate_id", "status", "disposition", "planned_disposition", "handoff_id", "candidate_sha256",
            "point_sha256", "result_sha256", "truth_ids") if key in row}
            for row in state.get("candidate_outcomes") or []]
        prior.update(contract=state["binding"]["contract"], state_sha256=_digest(state))
        if interrupted:
            prior["interrupted_adoption"] = interrupted_proof
        if partial:
            prior["partial_revalidation"] = partial_proof
        if zero:
            prior["zero_revalidation"] = zero_proof
        return {"status": "prepared", "binding": binding, "binding_sha256": binding_hash,
                "candidate_ids": [], "commit_bindings": [],
                "previous_contract_attempts": list(state.get("previous_contract_attempts") or []) + [prior]}
    if state is not None:
        if state.get("binding_sha256") != binding_hash or state.get("binding") != binding:
            raise ValueError("source_coverage_attempt_binding_changed")
        return state
    return {"status": "prepared", "binding": binding, "binding_sha256": binding_hash,
            "candidate_ids": [], "commit_bindings": []}


async def _prove_bound_retry(
    backend: Any, *, origin: Any, item: Any, prepared: dict[str, Any], config: Any,
    host_client: str, active_carrier_id: str | None = None, allow_active_owner: bool = False,
    partial: bool = False, zero: bool = False,
) -> dict[str, Any]:
    """Read-only proof before an interrupted v2 state, claim or dispatch changes."""
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt

    require = _require_origin
    require(origin.status == "failed" and origin.completed_at is not None and origin.trigger_source == "ide_hook",
            "source_coverage_interrupted_origin_not_terminal")
    state = (origin.continuation.get("source_coverage") or {}).get(item.source_id) or {}
    require(_zero_retryable(state) if zero else _partial_retryable(state) if partial else _interrupted_retryable(state),
            "source_coverage_zero_state_not_adoptable" if zero else
            "source_coverage_partial_state_not_adoptable" if partial else "source_coverage_interrupted_state_not_adoptable")
    binding = prepared["binding"]
    old_binding = {**state["binding"], "contract": CONTRACT}
    require(old_binding == binding, "source_coverage_attempt_binding_changed")
    _run, generation, trigger = await _bound_source_account(backend, run=origin,
        project_name=origin.project_name, project_root=str(prepared["job"].project_root),
        config=config, host_client=host_client)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
    active_reflection = None
    if active_carrier_id is not None:
        active = await backend.structured_store.get_dream_run(active_carrier_id)
        require(active is not None and active.status == "processing"
            and active.continuation.get("terminal_source_coverage_origin_run_id") == origin.id,
            "source_coverage_interrupted_active_owner_changed")
        active_reflection = active.reflection_job_id
    for reflection in backend.reflection_job_store.list(project_name=origin.project_name, status="processing", kind="dream"):
        stamp = reflection.updated_at if reflection.updated_at.tzinfo else reflection.updated_at.replace(tzinfo=timezone.utc)
        if stamp < cutoff:
            continue
        own = (allow_active_owner and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1"
            and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_GENERATION") == generation
            and reflection.source == "ide_hook" and origin.id in reflection.input_refs
            and Path(reflection.project_root).resolve() == Path(prepared["job"].project_root).resolve())
        require(reflection.id == active_reflection or own, "source_coverage_interrupted_processing_active")
    # A detached recheck may hold this same task's new lease. A foreground
    # nomination cannot adopt a live old lease merely because its generation matches.
    root = str(Path(prepared["job"].project_root).resolve())
    stem = hashlib.sha256(f"{host_client}\0{root}".encode()).hexdigest()[:24]
    lease = Path(backend.data_dir) / "hook_runtime" / "background" / f"{host_client}-{stem}.lock"
    if lease.is_file() and time.time() - lease.stat().st_mtime <= 300:
        try:
            owner = json.loads(lease.read_text(encoding="ascii"))
        except (ValueError, OSError):
            owner = {}
        require(os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1"
            and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_GENERATION") == generation
            and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_LEASE") == generation
            and owner.get("generation") == generation, "source_coverage_interrupted_worker_active")
    claims = (origin.continuation.get("terminal_coverage_takeover") or {}).get("claims") or {}
    old_claims = [(key, claim) for key, claim in claims.items()
        if claim.get("predecessor_id") == item.source_id and claim.get("source_binding_sha256") == state["binding_sha256"]]
    require(bool(old_claims), "source_coverage_interrupted_claim_missing")
    prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
    source_jobs = {note[len(prefix):].strip() for note in origin.notes or [] for prefix in prefixes if note.startswith(prefix)}
    require(len(source_jobs) == 1, "source_coverage_interrupted_original_job_unproved")
    closed = []
    for key, claim in old_claims:
        carrier = await backend.structured_store.get_dream_run(claim.get("carrier_run_id"))
        require(carrier is not None and carrier.id != active_carrier_id
            and carrier.project_name == origin.project_name and carrier.status in {"completed", "failed"}
            and carrier.completed_at is not None and carrier.trigger_source == "ide_hook"
            and carrier.continuation.get("terminal_source_coverage_origin_run_id") == origin.id
            and carrier.continuation.get("maintenance_scope") == origin.continuation.get("maintenance_scope")
            and (partial or carrier.reflection_job_id == claim.get("carrier_reflection_id"))
            and claim.get("origin_run_id") == origin.id,
            "source_coverage_interrupted_carrier_not_closed")
        result = (carrier.continuation.get("terminal_source_coverage") or {}).get(f"{origin.id}:{item.source_id}") or {}
        require((result.get("status") == "no_write" and result.get("reason") == "source_coverage_no_candidate"
                and claim.get("status") == "no_write" if zero else
                result.get("status") == "unresolved" and result.get("reason") == "source_coverage_partial_resolution"
                and claim.get("status") == "unresolved" if partial else
                result.get("status") == "blocked" and result.get("reason") == "terminal_coverage_runtime_changed")
            and result.get("origin_run_id") == origin.id and result.get("predecessor_id") == item.source_id,
            "source_coverage_interrupted_reason_unproved")
        reflection = backend.reflection_job_store.get(claim.get("carrier_reflection_id"))
        terminal_reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
        if partial:
            require(terminal_reflection is not None and terminal_reflection.status in {"completed", "failed"}
                and terminal_reflection.completed_at is not None and terminal_reflection.lease_owner is None
                and terminal_reflection.lease_until is None and terminal_reflection.project_name == origin.project_name
                and terminal_reflection.kind == "dream" and terminal_reflection.source == "ide_hook"
                and Path(terminal_reflection.project_root).resolve() == Path(root)
                and origin.id in terminal_reflection.input_refs and source_jobs.issubset(terminal_reflection.input_refs),
                "source_coverage_partial_final_reflection_not_closed")
        closed_reflection = reflection is not None and (reflection.status in {"completed", "failed"}
            or (partial and reflection.status == "retryable" and reflection.id != carrier.reflection_job_id
                and reflection.updated_at <= carrier.completed_at and reflection.lease_owner is None
                and reflection.lease_until is None))
        require(closed_reflection
            and (not zero or (reflection.completed_at is not None and reflection.lease_owner is None
                and reflection.lease_until is None))
            and reflection.project_name == origin.project_name and reflection.source == "ide_hook"
            and Path(reflection.project_root).resolve() == Path(root)
            and reflection.kind == "dream" and origin.id in reflection.input_refs
            and source_jobs.issubset(reflection.input_refs)
            and {identity for identity in reflection.input_refs
                if backend.transcript_store.get_distill_job(identity) is not None} == source_jobs,
            "source_coverage_interrupted_reflection_not_closed")
        closed.append({"claim_key": key, "claim_sha256": _digest(claim),
            "carrier_sha256": _digest(carrier.to_dict()), "reflection_sha256": _digest(reflection.to_dict()),
            **({"final_reflection_sha256": _digest(terminal_reflection.to_dict())} if partial else {})})
    receipts = []
    for note in origin.continuation.get("terminal_coverage_receipts") or []:
        prefix = "dream source coverage receipt: "
        if isinstance(note, str) and note.startswith(prefix):
            row = json.loads(note[len(prefix):])
            if row.get("attempt_id") == state["binding_sha256"]:
                receipts.append(row)
    def valid_hash(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
    require(not zero or valid_hash(state.get("decision_sha256")), "source_coverage_zero_decision_unproved")
    phases = {row.get("phase"): row for row in receipts}
    required_phases = ("decide",) if zero else ("decide", "candidate_verify", "assimilate", "final_scope") if partial else ("decide", "candidate_verify")
    require(all(phase in phases for phase in required_phases)
            and (not (partial or zero) or len(receipts) == len(required_phases)),
            "source_coverage_interrupted_native_receipt_missing")
    for receipt in receipts:
        attempts = receipt.get("native_attempts") or []
        require(receipt.get("source_job_id") == binding["source_job_id"] and receipt.get("schema_valid") is True
            and receipt.get("host_client") == host_client and valid_hash(receipt.get("input_sha256"))
            and valid_hash(receipt.get("response_sha256")) and bool(attempts)
            and all(native.get("status") == "completed" and native.get("terminal") == "completed"
                and native.get("model_dispatched") is True and native.get("unknown_response_usage_count") == 0
                and valid_hash(native.get("input_sha256")) and valid_hash(native.get("response_text_sha256"))
                for native in attempts), "source_coverage_interrupted_native_receipt_unproved")
        require(not zero or (len(attempts) == 1
            and attempts[0].get("input_sha256") == receipt["input_sha256"]
            and attempts[0].get("response_text_sha256") == receipt["response_sha256"]),
            "source_coverage_zero_native_binding_changed")
    packet = prepared["packet"]
    windows = {row["exchange_index"]: row for row in packet["semantic_decision_exchanges"]}
    _revision, rendering, _raw = _source_report_context(backend, project_name=origin.project_name,
        source_id=binding["source_id"], source_revision=binding["source_revision"])
    exchanges = _parse_exchanges(rendering)[1]
    verification = (phases.get("candidate_verify") or {}).get("verification_points") or []
    require(len(verification) == len(state["candidate_ids"]), "source_coverage_interrupted_candidate_proof_missing")
    decision_root = Path(backend.data_dir) / "job_workspaces" / "knowledge" / "decisions"
    for path in decision_root.glob("*.json") if state["candidate_ids"] else []:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        # Legacy unrelated proposals may use retired schema fields. Select by
        # the exact candidate first; never interpret them as this attempt.
        require(partial or (wrapper.get("data") or {}).get("candidate_id") not in state["candidate_ids"],
                "source_coverage_interrupted_prior_decision_exists")
    store = backend.structured_store.knowledge_store
    frozen = []
    for index, identity in enumerate(state["candidate_ids"]):
        candidate = await store.get_candidate(identity)
        evidence = await store.list_evidence(identity)
        outcome = next((row for row in state.get("candidate_outcomes") or [] if row.get("candidate_id") == identity), {})
        require(candidate is not None and candidate.project_name == origin.project_name
            and (candidate.status == outcome.get("status") if partial else candidate.status == "pending")
            and candidate.source_report is None
            and candidate.assimilation_disposition is None and not candidate.assimilation_target_ids
            and not candidate.assimilation_targets and len(evidence) == 1,
            "source_coverage_interrupted_candidate_changed")
        require(not partial or outcome.get("candidate_sha256") == _digest(candidate.to_dict()),
                "source_coverage_partial_candidate_outcome_changed")
        expected = str(uuid5(NAMESPACE_URL, f"harness-mem:autonomous-knowledge-candidate:{binding['source_job_id']}:"
            f"attempt:source-coverage:{state['binding_sha256']}:{index + 1}:{candidate.candidate_type}:{candidate.statement}"))
        proof = verification[index]
        native_hashes = {hashlib.sha256(candidate.statement.encode()).hexdigest()}
        if candidate.candidate_type == "rule":
            from harness_mem.commands.separated_assimilation import _statement
            from harness_mem.autonomous.worker import _candidate_statement_from_arguments
            # The common rule owner renders Chinese trigger separators as
            # '：'; the native candidate verifier renders the same typed rule
            # with ': '. Reconstruct only a round-tripping shared projection.
            for separator in ("：", ": "):
                for offset in range(len(candidate.statement)):
                    if not candidate.statement.startswith(separator, offset):
                        continue
                    arguments = {"kind": "rule", "trigger": candidate.statement[:offset],
                        "pattern": candidate.statement[offset + len(separator):]}
                    if " ".join(_statement(arguments, kind="rule").split()) == candidate.statement:
                        native_hashes.add(hashlib.sha256(_candidate_statement_from_arguments(arguments).encode()).hexdigest())
        require(identity == expected and proof.get("candidate_index") == index
            and proof.get("scope_text_sha256") in native_hashes,
            "source_coverage_interrupted_candidate_native_hash_changed")
        source = evidence[0]
        require(source.candidate_id == identity and source.project_name == origin.project_name
            and source.distill_job_id == binding["source_job_id"] and source.evidence_basis == "user_statement"
            and bool(source.verification_refs), "source_coverage_interrupted_evidence_changed")
        for ref in source.verification_refs:
            window = windows.get(ref.exchange_index)
            hashes = ({window["content_sha256"]} | {hashlib.sha256(value.encode()).hexdigest()
                for value in exchanges[ref.exchange_index - 1]["user"]}) if window else set()
            require(ref.kind == "user_statement" and ref.role == "user" and ref.locator is None
                and ref.content_sha256 in hashes, "source_coverage_interrupted_source_ref_changed")
        frozen.append({"candidate_id": identity, "candidate_sha256": _digest(candidate.to_dict()),
            "evidence_sha256": _digest([value.to_dict() for value in evidence]),
            **({"status": candidate.status} if partial else {})})
    account = read_task_budget_receipt(Path(backend.data_dir), maintenance_task_scope(trigger, generation))
    phase_slices = {"decide": "source-decide:" + binding["source_job_id"],
        "candidate_verify": "source-verify", "assimilate": "source-assimilate", "final_scope": "source-final-scope"}
    for receipt in receipts:
        suffix = phase_slices.get(receipt.get("phase"))
        require(suffix is not None, "source_coverage_interrupted_native_phase_changed")
        exact_slice = f"source-coverage:{origin.id}:{state['binding_sha256']}:{suffix}"
        calls = [call for call in account["calls"] if call.get("phase") == "dream"
            and call.get("slice_id") == exact_slice]
        require(bool(calls) and all(sum(call["usage"][key] for call in calls) == receipt.get(key)
            for key in ("input_tokens", "output_tokens")), "source_coverage_interrupted_native_account_changed")
        require(not zero or (len(calls) == 1 and len([call for call in account["calls"]
            if str(call.get("slice_id") or "").startswith(
                f"source-coverage:{origin.id}:{state['binding_sha256']}:")]) == 1),
            "source_coverage_zero_dispatch_count_changed")
    proof = {"contract": "source-coverage-zero-v4-revalidation-v1" if zero else
        "source-coverage-partial-v3-revalidation-v1" if partial else "source-coverage-interrupted-v2-adoption-v1",
        "state_sha256": _digest(state),
        "binding_sha256": _digest(binding), "old_binding_sha256": state["binding_sha256"],
        "closed_claims": closed, "candidates": frozen,
        "native_receipts_sha256": _digest(receipts), "account_sha256": _digest(account)}
    if partial:
        proof.update(await _partial_commit_proofs(backend, origin=origin, prepared=prepared,
            state=state, final_receipt=phases["final_scope"]))
    if zero:
        proof["retained_partial_sha256"] = await _assert_partial_history(backend, state, binding)
    return proof


async def _prove_interrupted_retry(backend: Any, **kwargs: Any) -> dict[str, Any]:
    return await _prove_bound_retry(backend, **kwargs)


async def _prove_partial_retry(backend: Any, **kwargs: Any) -> dict[str, Any]:
    return await _prove_bound_retry(backend, **kwargs, partial=True)


async def _prove_zero_retry(backend: Any, **kwargs: Any) -> dict[str, Any]:
    return await _prove_bound_retry(backend, **kwargs, zero=True)


async def _assert_partial_history(backend: Any, state: Mapping[str, Any], binding: Mapping[str, Any]) -> list[str]:
    """Freeze previous partial writes through the one no-write contract change."""
    from harness_mem.commands.dream_continuation import _require_origin as require
    hashes = []
    zero_history = [previous for previous in state.get("previous_contract_attempts") or []
        if previous.get("zero_revalidation") is not None]
    for previous in zero_history:
        zero = previous["zero_revalidation"]
        require(previous.get("contract") == _ZERO_CONTRACT and previous.get("status") == "no_write"
            and previous.get("reason_code") == "source_coverage_no_candidate"
            and previous.get("candidate_ids") == [] and previous.get("commit_bindings") == []
            and zero.get("contract") == "source-coverage-zero-v4-revalidation-v1"
            and zero.get("binding_sha256") == _digest(binding)
            and zero.get("old_binding_sha256") == previous.get("binding_sha256")
            and zero.get("state_sha256") == previous.get("state_sha256"),
            "source_coverage_zero_history_proof_changed")
    for previous in state.get("previous_contract_attempts") or []:
        proof = previous.get("partial_revalidation")
        if proof is None:
            continue
        allowed = {_digest(binding)}
        if _zero_retryable(state) or zero_history:
            allowed.add(_digest({**binding, "contract": _ZERO_CONTRACT}))
        require(proof.get("contract") == "source-coverage-partial-v3-revalidation-v1"
            and proof.get("binding_sha256") in allowed
            and proof.get("old_binding_sha256") == previous.get("binding_sha256"),
            "source_coverage_partial_history_proof_changed")
        await _assert_partial_snapshot(backend, proof)
        hashes.append(_digest(proof))
    require(all(previous["zero_revalidation"].get("retained_partial_sha256") == hashes
                for previous in zero_history), "source_coverage_zero_partial_history_changed")
    return hashes


async def _partial_commit_proofs(
    backend: Any, *, origin: Any, prepared: Mapping[str, Any], state: Mapping[str, Any], final_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind already committed adds and the exact incomplete-update deferral."""
    from harness_mem.commands.dream_continuation import _require_origin
    require = _require_origin
    canonical, store = backend.structured_store._canonical, backend.structured_store.knowledge_store
    outcomes = {row["candidate_id"]: row for row in state["candidate_outcomes"]}
    commits = state["commit_bindings"]
    require({row["candidate_id"] for row in commits}
        == {key for key, row in outcomes.items() if row["disposition"] == "add"}
        and len({row["candidate_id"] for row in commits}) == len(commits)
        and (state.get("result_status_counts") or {}).get("promoted") == len(commits),
        "source_coverage_partial_commit_inventory_changed")
    native_scopes = {row.get("scope_text_sha256") for row in final_receipt.get("verification_points") or []
        if row.get("semantic_support") == "supported" and row.get("future_scope") == "durable"
        and row.get("source_use") == "standing_decision"}
    retained, transactions = [], []
    for commit in commits:
        outcome = outcomes[commit["candidate_id"]]
        identities = commit.get("truth_ids") or []
        require(bool(identities) and len(set(identities)) == len(identities)
            and identities == outcome.get("truth_ids") and len(identities) == len(commit.get("truth_sha256") or []),
            "source_coverage_partial_commit_inventory_changed")
        transaction = canonical.payload_transaction_result("knowledge-change:" + commit["decision_id"])
        require(isinstance(transaction, dict), "source_coverage_partial_commit_not_persisted")
        writes = {(row.get("collection"), row.get("entity_id")): row for row in transaction.get("mutations") or []}
        transactions.append({"decision_id": commit["decision_id"], "transaction_sha256": _digest(transaction)})
        for identity, semantic in zip(identities, commit["truth_sha256"]):
            entry = await store.get_entry(identity, project_name=origin.project_name)
            raw = canonical.get_payload_json("knowledge_entries", identity)
            require(entry is not None and entry.source_report is None and raw is not None
                and _digest({"title": entry.title, "statement": entry.statement, "topic_path": entry.module_path}) == semantic
                and hashlib.sha256((entry.title + "\n" + entry.statement).encode()).hexdigest() in native_scopes,
                "source_coverage_partial_committed_truth_changed")
            digest = hashlib.sha256(raw.encode()).hexdigest()
            write = writes.get(("knowledge_entries", identity)) or {}
            require(write.get("operation") == "upsert" and write.get("payload_sha256") == digest,
                    "source_coverage_partial_commit_payload_changed")
            sources = await store.list_sources(identity)
            source_rows = []
            require(bool(sources), "source_coverage_partial_committed_sources_missing")
            for source in sources:
                outcome, _reason, content, truncated, _effective = _reopen_complete_user_context(backend, source)
                body = json.loads(content) if content and outcome == "verified" and not truncated else {}
                source_raw = canonical.get_payload_json("knowledge_sources", source.id)
                source_write = writes.get(("knowledge_sources", source.id)) or {}
                require(source.source_kind == "user_statement" and source.project_name == origin.project_name
                    and source.knowledge_id == identity and body.get("role") == "user"
                    and body.get("source_id") == prepared["binding"]["source_id"]
                    and body.get("source_revision") == prepared["binding"]["source_revision"]
                    and body.get("context_scope") == "complete-authored-user-v1" and source_raw is not None
                    and source_write.get("operation") == "upsert"
                    and source_write.get("payload_sha256") == hashlib.sha256(source_raw.encode()).hexdigest(),
                    "source_coverage_partial_committed_sources_changed")
                source_rows.append({"source_id": source.id, "payload_sha256": hashlib.sha256(source_raw.encode()).hexdigest()})
            retained.append({"entry_id": identity, "payload_sha256": digest,
                "sources": sorted(source_rows, key=lambda row: row["source_id"])})
    decision_root = Path(backend.data_dir) / "job_workspaces" / "knowledge" / "decisions"
    decisions = [json.loads(path.read_text(encoding="utf-8")) for path in decision_root.glob("*.json")]
    deferred = []
    reason = "Final knowledge scope verification deferred this complete point: final_update_meaning_incomplete."
    for identity, outcome in outcomes.items():
        if outcome["disposition"] == "add":
            continue
        found = [row["data"] for row in decisions if (row.get("data") or {}).get("candidate_id") == identity]
        require(len(found) == 1 and found[0].get("project_name") == origin.project_name
            and found[0].get("disposition") == "defer" and found[0].get("reason") == reason
            and not found[0].get("canonical_truth_ids") and not found[0].get("predecessor_truth_ids"),
            "source_coverage_partial_defer_reason_unproved")
        handoff_id = outcome.get("handoff_id")
        raw = canonical.get_payload_json("task_handoffs", handoff_id) if isinstance(handoff_id, str) else None
        handoff = json.loads(raw) if raw is not None else {}
        require(handoff.get("project_name") == origin.project_name and handoff.get("status") == "in_progress"
            and (handoff.get("context") or {}).get("candidate_id") == identity
            and (handoff.get("context") or {}).get("distill_job_id") == prepared["binding"]["source_job_id"]
            and any(reason in step for step in handoff.get("next_steps") or []),
            "source_coverage_partial_handoff_changed")
        deferred.append({"candidate_id": identity, "decision_id": found[0]["id"],
            "decision_sha256": _digest(found[0]), "handoff_id": handoff_id,
            "handoff_sha256": hashlib.sha256(raw.encode()).hexdigest()})
    require(bool(deferred), "source_coverage_partial_defer_reason_unproved")
    return {"committed_truth": retained, "committed_transactions": transactions, "deferred": deferred}


async def _assert_partial_snapshot(backend: Any, proof: Mapping[str, Any]) -> None:
    """Never replay old adds or adopt concurrent changes to retained records."""
    await _assert_interrupted_candidates(backend, proof)
    canonical, store = backend.structured_store._canonical, backend.structured_store.knowledge_store
    for row in proof["committed_truth"]:
        raw = canonical.get_payload_json("knowledge_entries", row["entry_id"])
        if raw is None or hashlib.sha256(raw.encode()).hexdigest() != row["payload_sha256"]:
            raise ValueError("source_coverage_partial_retained_truth_snapshot_changed")
        sources = await store.list_sources(row["entry_id"])
        if {value.id for value in sources} != {value["source_id"] for value in row["sources"]}:
            raise ValueError("source_coverage_partial_retained_sources_snapshot_changed")
        for source in row["sources"]:
            raw = canonical.get_payload_json("knowledge_sources", source["source_id"])
            if raw is None or hashlib.sha256(raw.encode()).hexdigest() != source["payload_sha256"]:
                raise ValueError("source_coverage_partial_retained_sources_snapshot_changed")
    for row in proof["committed_transactions"]:
        transaction = canonical.payload_transaction_result("knowledge-change:" + row["decision_id"])
        if _digest(transaction) != row["transaction_sha256"]:
            raise ValueError("source_coverage_partial_commit_snapshot_changed")
    for row in proof["deferred"]:
        path = Path(backend.data_dir) / "job_workspaces" / "knowledge" / "decisions" / (
            hashlib.sha256(row["decision_id"].encode()).hexdigest() + ".json")
        decision = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        raw = canonical.get_payload_json("task_handoffs", row["handoff_id"])
        if (_digest(decision.get("data")) != row["decision_sha256"] or raw is None
                or hashlib.sha256(raw.encode()).hexdigest() != row["handoff_sha256"]):
            raise ValueError("source_coverage_partial_defer_snapshot_changed")


async def _assert_interrupted_candidates(backend: Any, proof: Mapping[str, Any]) -> None:
    store = backend.structured_store.knowledge_store
    for row in proof["candidates"]:
        candidate = await store.get_candidate(row["candidate_id"])
        evidence = await store.list_evidence(row["candidate_id"])
        if (candidate is None or candidate.status != row.get("status", "pending")
                or _digest(candidate.to_dict()) != row["candidate_sha256"]
                or _digest([value.to_dict() for value in evidence]) != row["evidence_sha256"]):
            raise ValueError("source_coverage_interrupted_candidate_snapshot_changed")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _failure_context_digest(prepared: Mapping[str, Any]) -> str:
    return _digest({key: prepared[key] for key in (
        "binding", "packet", "authored_user_exchanges", "successors", "comparison_current_truth")})


def _terminal_failed_account_proof(account: Mapping[str, Any]) -> dict[str, Any]:
    """A metadata-only witness; the common account owner still validates it."""
    from harness_mem.commands.dream_continuation import _require_origin
    calls = account.get("calls")
    _require_origin(isinstance(calls, list) and len(calls) > 1, "source_coverage_failure_terminal_unproved")
    failed = calls[-1]
    _require_origin(failed.get("status") == "failed" and type(failed.get("usage_exact")) is bool
        and failed.get("reconciled_at") is not None
        and (failed.get("usage_exact") is True or failed.get("usage") == {
            "input_tokens": None, "output_tokens": None, "duration_seconds": None})
        and all(row.get("status") in {"completed", "failed"} and row.get("usage_exact") is True for row in calls[:-1]),
        "continuation_usage_unknown_or_active")
    return {"contract": "source-failure-bookkeeping-v1", "task_scope": account.get("task_scope"),
        "ledger_sha256": _digest(account), "failed_call_id": failed.get("call_id"),
        "failed_call_sha256": _digest(failed), "completed_prefix_sha256": _digest(calls[:-1])}


async def _persist_terminal_source_checkpoint(
    backend: Any, *, origin: Any, expected_sha: str, mutations: list[dict[str, Any]],
    terminal_child: Any | None = None,
) -> str:
    """Existing canonical source checkpoint writer, including terminal bookkeeping."""
    canonical = backend.structured_store._canonical
    payload = origin.to_dict()
    identity = {"before": expected_sha, "after": payload}
    if terminal_child is not None:
        identity["terminal_child"] = terminal_child.to_dict()
    await asyncio.to_thread(canonical.apply_payload_transaction,
        idempotency_key="terminal-coverage-checkpoint:" + _digest(identity), mutations=mutations)
    saved = canonical.get_payload_json("dream_runs", origin.id)
    if saved is None or _digest(json.loads(saved)) != _digest(payload):
        raise CanonicalTransactionPreconditionError("terminal_coverage_checkpoint_readback_changed")
    if terminal_child is not None:
        child = canonical.get_payload_json("dream_runs", terminal_child.id)
        if child is None or _digest(json.loads(child)) != _digest(terminal_child.to_dict()):
            raise CanonicalTransactionPreconditionError("terminal_coverage_checkpoint_readback_changed")
        projection = {key: getattr(terminal_child, key) for key in (
            "id", "project_name", "started_at", "completed_at", "status", "trigger_source",
            "reflection_job_id", "policy_version", "duration_ms")}
        index = backend.structured_store._index
        if index.get("dream_runs", terminal_child.id) is None:
            await asyncio.to_thread(index.insert, "dream_runs", projection)
        else:
            await asyncio.to_thread(index.update, "dream_runs", terminal_child.id, projection)
    return hashlib.sha256(saved.encode()).hexdigest()


def _scope_fingerprint(entry: Any) -> str:
    report = entry.source_report.model_dump(mode="json") if entry.source_report else None
    return _digest({"title": entry.title, "statement": entry.statement,
                    "module_path": list(entry.module_path), "source_report": report})


def _original_fingerprint(checkpoint: Mapping[str, Any], notes: Sequence[str], identity: str) -> str:
    saved = (checkpoint.get("verification") or {}).get(identity) or {}
    found = saved.get("semantic_fingerprint")
    if isinstance(found, str) and len(found) == 64:
        return found
    for note in reversed(notes):
        prefix = "dream target snapshots: "
        if note.startswith(prefix):
            try:
                for row in json.loads(note[len(prefix):]):
                    if row.get("entry_id") == identity and isinstance(row.get("fingerprint"), str):
                        return row["fingerprint"]
            except (ValueError, TypeError):
                continue
    raise ValueError("source_coverage_original_fingerprint_missing")


async def _current_source_comparison(
    backend: Any, *, project_name: str, project_root: str | Path, original_revision: Any,
    original_windows: Sequence[Mapping[str, Any]], successor_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Read existing same-source coverage without adding evidence or write targets."""
    store = backend.structured_store.knowledge_store
    original_anchors = {row["exchange_index"]: row["content_sha256"] for row in original_windows}
    opened: dict[tuple[str, str], tuple[dict[str, Any], Any] | None] = {}
    comparisons = []
    for entry in await store.list_entries(project_name, project_root=project_root):
        if entry.project_name != project_name or entry.source_report is not None or entry.id in successor_ids:
            continue
        try:
            sources = await store.list_sources(entry.id)
            if not sources or any(source.source_kind != "user_statement"
                    or source.project_name != project_name or source.knowledge_id != entry.id for source in sources):
                continue
            valid, shared_anchor = True, False
            for source in sources:
                query = parse_qs(urlparse(source.locator).fragment)
                if (query.get("source_id") != [original_revision.source_id]
                        or len(query.get("source_revision", [])) != 1 or len(query.get("exchange", [])) != 1):
                    valid = False
                    break
                key = (source.locator, source.content_sha256)
                if key not in opened:
                    outcome, _reason, content, truncated, _effective = _reopen_complete_user_context(backend, source)
                    revision = backend.transcript_store.get_revision(original_revision.source_id, query["source_revision"][0])
                    body = json.loads(content) if outcome == "verified" and content and not truncated else None
                    opened[key] = (body, revision) if body is not None and revision is not None else None
                value = opened[key]
                if value is None:
                    valid = False
                    break
                body, revision = value
                if (body.get("context_scope") != "complete-authored-user-v1" or body.get("role") != "user"
                        or body.get("project_name") != project_name or body.get("source_id") != original_revision.source_id
                        or body.get("source_revision") != query["source_revision"][0]
                        or body.get("session_id") != original_revision.session_id
                        or revision.project_name != project_name or revision.client != original_revision.client
                        or revision.session_id != original_revision.session_id
                        or Path(revision.project_root).resolve() != Path(project_root).resolve()):
                    valid = False
                    break
                anchor = (query.get("anchor_sha256") or [source.content_sha256])[0]
                shared_anchor |= original_anchors.get(int(query["exchange"][0])) == anchor
            if not valid or not shared_anchor:
                continue
            snapshot = _entry_version_snapshot(entry)
            current = await store.get_entry(entry.id, project_name=project_name, project_root=project_root)
            if current is None or _entry_version_snapshot(current) != snapshot:
                continue
            comparisons.append({**snapshot, "comparison_only": True,
                "kind": "current_knowledge_comparison_not_source_evidence"})
        except (ValueError, KeyError, TypeError, OSError):
            # A missing or invalid comparison source does not authorize a claim
            # and must not invalidate the original independently proved source.
            continue
    return sorted(comparisons, key=lambda row: row["id"])


async def _prepare(
    backend: Any, *, project_name: str, project_root: str | Path,
    run_id: str, item: Any, checkpoint: Mapping[str, Any], notes: Sequence[str],
    include_current_comparison: bool = False,
) -> dict[str, Any] | None:
    """Reopen an exact retained revision and its completed job without preparing it."""
    store = backend.structured_store.knowledge_store
    if item.source_id not in set(checkpoint.get("target_ids") or []):
        raise ValueError("source_coverage_predecessor_outside_original_manifest")
    if await store.get_entry(item.source_id, project_name=project_name, project_root=project_root) is not None:
        raise ValueError("source_coverage_predecessor_still_current")
    successor_ids = list(dict.fromkeys(str(value) for value in item.result.get("truth_ids") or []))
    if not successor_ids:
        raise ValueError("source_coverage_successors_missing")
    successors = []
    all_sources = []
    for identity in successor_ids:
        entry = await store.get_entry(identity, project_name=project_name, project_root=project_root)
        if entry is None:
            raise ValueError("source_coverage_successor_changed")
        if entry.source_report is not None:
            return None
        successors.append(entry)
        sources = await store.list_sources(identity)
        if not sources:
            raise ValueError("source_coverage_retained_source_missing")
        # Other authorities retain their own maintenance path. An ordinary
        # source-report or repository ref never becomes authored user evidence.
        if not any(source.source_kind == "user_statement" for source in sources):
            return None
        if any(source.source_kind != "user_statement" for source in sources):
            raise ValueError("source_coverage_mixed_authority")
        all_sources.extend(sources)
    reopened = []
    for source in all_sources:
        outcome, _reason, content, truncated, effective = _reopen_complete_user_context(backend, source)
        if outcome != "verified" or not content or truncated:
            raise ValueError("source_coverage_original_user_source_unproved")
        body = json.loads(content)
        if (body.get("project_name") != project_name or body.get("role") != "user"
                or body.get("context_scope") != "complete-authored-user-v1"):
            raise ValueError("source_coverage_user_context_scope_changed")
        reopened.append((source, effective, body, content))
    contexts = {_digest(body) for _source, _effective, body, _content in reopened}
    if len(contexts) != 1:
        raise ValueError("source_coverage_cross_revision_group")
    source, effective, body, content = reopened[0]
    source_id, revision_id = body["source_id"], body["source_revision"]
    revision, rendering, _raw = _source_report_context(
        backend, project_name=project_name, source_id=source_id, source_revision=revision_id,
    )
    if Path(revision.project_root).resolve() != Path(project_root).resolve():
        raise ValueError("source_coverage_project_root_changed")
    jobs = [job for job in backend.transcript_store.list_distill_jobs(project_name=project_name, status="completed")
            if job.source_id == source_id and job.source_revision == revision_id
            and job.session_id == revision.session_id and job.client == revision.client
            and Path(job.project_root).resolve() == Path(project_root).resolve()]
    if not jobs:
        raise ValueError("source_coverage_completed_source_job_missing")
    # All matching jobs must describe the same complete input. Use a stable
    # existing identity, never enqueue, reset, lease or re-finalize that job.
    job = sorted(jobs, key=lambda value: value.id)[0]
    audit, receipt = job.structural_audit, job.promotion_summary.get("readback")
    if (job.completed_chunk_count != job.expected_chunk_count
            or audit.get("coverage") != "complete"
            or audit.get("expected_chunks") != job.expected_chunk_count
            or audit.get("completed_chunks") != job.expected_chunk_count
            or not isinstance(receipt, dict) or receipt.get("verified") is not True
            or receipt.get("source_revision") != revision_id or job.completion_disposition is None):
        raise ValueError("source_coverage_completed_source_receipt_unproved")
    indexes = [row["exchange_index"] for row in body["authored_exchanges"]]
    if not indexes or len(indexes) != len(set(indexes)):
        raise ValueError("source_coverage_user_inventory_invalid")
    windows = render_distill_exchange_windows(rendering, indexes)
    if len(windows) != len(indexes):
        raise ValueError("source_coverage_user_windows_incomplete")
    _header, exchanges, _summary = _parse_exchanges(rendering)
    for window in windows:
        preceding = exchanges[window["exchange_index"] - 1]["assistant"][:-1]
        if preceding:
            window["preceding_assistant_messages"] = list(preceding)
    anchors = sorted({int(parse_qs(urlparse(row[0].locator).fragment)["exchange"][0]) for row in reopened})
    refs = [{"exchange_index": row["exchange_index"], "content_sha256": row["content_sha256"]}
            for row in windows if row["exchange_index"] in anchors][:8]
    if not refs:
        raise ValueError("source_coverage_original_anchor_missing")
    binding = {
        "contract": CONTRACT, "run_id": run_id, "predecessor_id": item.source_id,
        "predecessor_sha256": _original_fingerprint(checkpoint, notes, item.source_id),
        "successor_ids": successor_ids,
        "successor_sha256": [_scope_fingerprint(entry) for entry in successors],
        "source_id": source_id, "source_revision": revision_id,
        "source_job_id": job.id, "source_job_sha256": _digest(job.to_dict()),
        "context_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "source_refs_sha256": _digest([{"id": row.id, "locator": row.locator,
            "digest": row.content_sha256} for row in all_sources]),
    }
    checks = {key: "absent" for key in (
        "user_correction", "explicit_decision", "successful_solution", "repeated_failure",
        "rule_or_preference", "reusable_workflow_or_fact", "version_or_migration", "unfinished_handoff")}
    packet = {
        "project_name": project_name, "source_id": source_id, "source_revision": revision_id,
        "distill_job_id": job.id, "semantic_decision_exchanges": windows,
        "semantic_evidence": {"output_exchange_count": len(windows)},
        "zero_candidate_exchange_refs": refs,
        "zero_candidate_challenge_template": {
            "version": "v1", "source_revision": revision_id, "evidence_fidelity": "complete",
            "future_utility": "none", "checks": checks, "inspected_exchange_refs": refs,
            "conclusion": "no_durable_candidate", "rationale": "No independently useful omitted claim was found in this bounded source coverage check.",
        },
    }
    authored = [{"exchange_index": row["exchange_index"], "message_index": index,
                "role": "user", "text": message, "sha256": hashlib.sha256(message.encode()).hexdigest(),
                "anchor_sha256": next(window["content_sha256"] for window in windows
                    if window["exchange_index"] == row["exchange_index"])}
        for row in body["authored_exchanges"] for index, message in enumerate(row["messages"])]
    return {"binding": binding, "packet": packet, "job": job, "authored_user_exchanges": authored,
            "successors": [_entry_version_snapshot(entry) for entry in successors],
            "successor_entries": tuple(successors),
            "comparison_current_truth": (await _current_source_comparison(backend,
                project_name=project_name, project_root=project_root, original_revision=revision,
                original_windows=windows, successor_ids=successor_ids)) if include_current_comparison else []}


EXPLICIT_REPAIR_CONTRACT = "explicit-dream-source-repair-v1"


async def _explicit_repair_origin(backend: Any, *, project_name: str,
                                  project_root: str | Path, run_id: str,
                                  origin_run_id: str) -> tuple[Any, dict[str, Any]]:
    """Read old history and its exact account; never resume or alter either."""
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt
    from harness_mem.config.merge import load_merged_config
    require = _require_origin
    origin = await backend.structured_store.get_dream_run(origin_run_id)
    require(bool(run_id) and run_id != origin_run_id and origin is not None
            and origin.project_name == project_name and origin.status == "failed"
            and origin.completed_at is not None and origin.trigger_source == "ide_hook",
            "source_coverage_repair_origin_invalid")
    scope = origin.continuation.get("maintenance_scope") or {}
    task_scope = maintenance_task_scope(scope.get("trigger_id", ""), scope.get("dispatch_generation", ""))
    account = read_task_budget_receipt(Path(backend.data_dir), task_scope)
    require(isinstance(account, dict) and isinstance(account.get("calls"), list)
            and bool(account["calls"]), "source_coverage_repair_account_missing")
    failure = (_terminal_failed_account_proof(account)
               if account["calls"][-1].get("status") == "failed" else None)
    await _bound_source_account(backend, run=origin, project_name=project_name,
        project_root=str(project_root), config=load_merged_config(project_root),
        host_client=account.get("host_client"), require_remaining=False, failure_account=failure)
    return origin, account


async def _explicit_current_rows(backend: Any, prepared: Mapping[str, Any], *,
                                  project_name: str, project_root: str | Path) -> tuple[dict[str, Any], tuple[Any, ...]]:
    store = backend.structured_store.knowledge_store
    entries = list(prepared["successor_entries"])
    for row in prepared["comparison_current_truth"]:
        entry = await store.get_entry(row["id"], project_name=project_name, project_root=project_root)
        if entry is None or _entry_version_snapshot(entry) != {key: value for key, value in row.items()
                if key not in {"comparison_only", "kind"}}:
            raise ValueError("source_coverage_repair_comparison_changed")
        entries.append(entry)
    snapshots = {}
    for entry in entries:
        snapshots[entry.id] = {"payload_sha256": _digest(entry.to_dict()),
            "scope_sha256": _digest(_entry_version_snapshot(entry)),
            "sources_sha256": _digest([value.to_dict() for value in await store.list_sources(entry.id)])}
    return snapshots, tuple(entries)


async def prepare_explicit_source_repair(backend: Any, *, project_name: str,
        project_root: str | Path, run_id: str, origin_run_id: str,
        predecessor_ids: Sequence[str]) -> dict[str, Any]:
    """Freeze explicit original-source work in a new task's candidate namespace."""
    identities = list(predecessor_ids)
    if (not identities or any(not isinstance(value, str) or not value for value in identities)
            or len(set(identities)) != len(identities)):
        raise ValueError("source_coverage_repair_selection_invalid")
    origin, account = await _explicit_repair_origin(backend, project_name=project_name,
        project_root=project_root, run_id=run_id, origin_run_id=origin_run_id)
    applied = {item.source_id: item for item in origin.items if item.final_action == "applied"
               and item.result.get("truth_change") in {"refine", "replace"}}
    bindings = {}
    for identity in identities:
        if identity not in applied:
            raise ValueError("source_coverage_repair_applied_item_missing")
        prepared = await _prepare(backend, project_name=project_name, project_root=project_root,
            run_id=run_id, item=applied[identity], checkpoint=origin.continuation,
            notes=origin.notes or [], include_current_comparison=True)
        if prepared is None:
            raise ValueError("source_coverage_repair_source_not_authored_user")
        _assert_original_successors(origin, applied[identity], prepared)
        # This is a new explicitly authorized source check, not adoption of an
        # earlier retry. Its old partial outputs may have been legitimately
        # replaced since then. Freeze actual current comparisons below; retain
        # the complete old run and account hashes without reopening their work.
        snapshots, _entries = await _explicit_current_rows(backend, prepared,
            project_name=project_name, project_root=project_root)
        bindings[identity] = {"binding": prepared["binding"],
            "binding_sha256": _digest(prepared["binding"]),
            "context_sha256": _failure_context_digest(prepared), "current_rows": snapshots}
    raw = backend.structured_store._canonical.get_payload_json("dream_runs", origin.id)
    if raw is None or _digest(json.loads(raw)) != _digest(origin.to_dict()):
        raise ValueError("source_coverage_repair_origin_changed")
    return {"contract": EXPLICIT_REPAIR_CONTRACT, "project_name": project_name,
        "project_root_sha256": _digest(str(Path(project_root).resolve())), "run_id": run_id,
        "origin_run_id": origin.id, "origin_payload_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "origin_task_scope": account["task_scope"], "origin_account_sha256": _digest(account),
        "host_client": account["host_client"], "predecessor_ids": identities, "source_bindings": bindings}


async def run_explicit_source_repair(backend: Any, *, project_name: str,
        project_root: str | Path, run_id: str, manifest: dict[str, Any],
        checkpoint: dict[str, Any], notes: list[str], provider: Any,
        persist: Callable[[], Awaitable[None]],
        boundary: Callable[[], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Reuse extraction, verification and canonical application on the fresh ledger."""
    if manifest.get("contract") == "explicit-source-handoff-recovery-v1":
        from harness_mem.commands.source_handoff_recovery import run_source_handoff_recovery
        return await run_source_handoff_recovery(backend, project_name=project_name,
            project_root=project_root, run_id=run_id, manifest=manifest,
            checkpoint=checkpoint, notes=notes, provider=provider, persist=persist, boundary=boundary)
    if manifest.get("contract") == "explicit-dream-source-audit-v1":
        from harness_mem.commands.dream_source_audit import run_explicit_source_audit
        return await run_explicit_source_audit(backend, project_name=project_name,
            project_root=project_root, run_id=run_id, manifest=manifest,
            checkpoint=checkpoint, notes=notes, provider=provider, persist=persist, boundary=boundary)
    from harness_mem.commands.dream_continuation import _require_origin
    require = _require_origin
    require(manifest.get("contract") == EXPLICIT_REPAIR_CONTRACT
        and manifest.get("run_id") == run_id and manifest.get("project_name") == project_name
        and manifest.get("project_root_sha256") == _digest(str(Path(project_root).resolve())),
        "source_coverage_repair_manifest_changed")
    binding = getattr(provider, "task_budget_binding", None)
    require(binding is not None and binding.task_scope != manifest.get("origin_task_scope")
        and binding.host_client == manifest.get("host_client")
        and Path(binding.data_dir).resolve() == Path(backend.data_dir).resolve()
        and getattr(provider, "host_client", None) == manifest.get("host_client"),
        "source_coverage_repair_new_account_required")
    fixed_scope = binding.task_scope
    origin, _account = await _explicit_repair_origin(backend, project_name=project_name,
        project_root=project_root, run_id=run_id, origin_run_id=manifest["origin_run_id"])
    identities = manifest.get("predecessor_ids")
    require(isinstance(identities, list) and bool(identities) and len(set(identities)) == len(identities)
        and set(manifest.get("source_bindings") or {}) == set(identities),
        "source_coverage_repair_manifest_changed")
    items = {item.source_id: item for item in origin.items if item.final_action == "applied"
             and item.result.get("truth_change") in {"refine", "replace"}}
    require(set(identities) <= set(items), "source_coverage_repair_applied_item_missing")
    state = checkpoint.setdefault("repair_source_coverage", {
        "contract": EXPLICIT_REPAIR_CONTRACT, "manifest_sha256": _digest(manifest),
        "task_scope": fixed_scope, "source_coverage": {}})
    require(state.get("manifest_sha256") == _digest(manifest) and state.get("task_scope") == fixed_scope,
            "source_coverage_repair_attempt_changed")
    shadow = {"target_ids": list(origin.continuation.get("target_ids") or []),
        "verification": origin.continuation.get("verification") or {},
        "slice_count": checkpoint.get("slice_count", 1), "source_coverage": state["source_coverage"]}
    shadow_notes = list(origin.notes or [])

    async def validate() -> None:
        old, account = await _explicit_repair_origin(backend, project_name=project_name,
            project_root=project_root, run_id=run_id, origin_run_id=manifest["origin_run_id"])
        raw = backend.structured_store._canonical.get_payload_json("dream_runs", old.id)
        require(raw is not None and hashlib.sha256(raw.encode()).hexdigest() == manifest["origin_payload_sha256"]
            and _digest(account) == manifest["origin_account_sha256"], "source_coverage_repair_origin_changed")
        require(getattr(provider, "task_budget_binding", None) is binding and binding.task_scope == fixed_scope,
                "source_coverage_repair_new_account_changed")
        for identity in identities:
            frozen = manifest["source_bindings"][identity]
            require(_digest(frozen["binding"]) == frozen["binding_sha256"]
                and frozen["binding"].get("run_id") == run_id,
                "source_coverage_repair_manifest_changed")
            attempt = state["source_coverage"].get(identity) or {}
            recovered = (await _recover_committed(backend, attempt, project_name=project_name,
                project_root=project_root)) if attempt.get("commit_bindings") else False
            changed = {value for proof in attempt.get("commit_bindings") or []
                if proof.get("status") == "applied" for value in proof.get("predecessor_ids") or []}
            for current_id, expected in frozen["current_rows"].items():
                if recovered and current_id in changed:
                    continue
                current = await backend.structured_store.knowledge_store.get_entry(current_id,
                    project_name=project_name, project_root=project_root)
                require(current is not None and _digest(current.to_dict()) == expected["payload_sha256"]
                    and _digest([value.to_dict() for value in
                        await backend.structured_store.knowledge_store.list_sources(current_id)]) == expected["sources_sha256"],
                    "source_coverage_repair_current_changed")
            job = backend.transcript_store.get_distill_job(frozen["binding"]["source_job_id"])
            require(job is not None and _digest(job.to_dict()) == frozen["binding"]["source_job_sha256"],
                    "source_coverage_repair_source_changed")
            _source_report_context(backend, project_name=project_name,
                source_id=frozen["binding"]["source_id"], source_revision=frozen["binding"]["source_revision"])
            if not recovered:
                fresh = await _prepare(backend, project_name=project_name, project_root=project_root,
                    run_id=run_id, item=items[identity], checkpoint=shadow, notes=shadow_notes,
                    include_current_comparison=True)
                require(fresh is not None and _failure_context_digest(fresh) == frozen["context_sha256"],
                        "source_coverage_repair_source_changed")

    async def guarded_prepare(prepared: dict[str, Any]) -> None:
        await validate()
        frozen = manifest["source_bindings"][prepared["binding"]["predecessor_id"]]
        require(_failure_context_digest(prepared) == frozen["context_sha256"],
                "source_coverage_repair_source_changed")
        snapshots, entries = await _explicit_current_rows(backend, prepared,
            project_name=project_name, project_root=project_root)
        require(snapshots == frozen["current_rows"], "source_coverage_repair_current_changed")
        # The existing common transaction checks these rows, but its allowed
        # mutation targets still contain only the actual current successors.
        prepared["successor_entries"] = entries

    note_count = len(shadow_notes)
    async def save() -> None:
        nonlocal note_count
        await validate()
        notes.extend(shadow_notes[note_count:])
        note_count = len(shadow_notes)
        state["source_coverage"] = shadow["source_coverage"]
        await persist()

    await validate()
    worked = await run_applied_source_coverage(backend, project_name=project_name,
        project_root=project_root, run_id=run_id, checkpoint=shadow, notes=shadow_notes,
        items=[items[value] for value in identities], provider=provider, persist=save,
        boundary=boundary, prepare_guard=guarded_prepare)
    statuses = [(shadow["source_coverage"].get(value) or {}).get("status") for value in identities]
    pending = any(value not in _TERMINAL for value in statuses)
    return {"worked": worked, "pending": pending,
        "status": "pending" if pending else "applied" if all(value == "applied" for value in statuses)
            else "no_write" if all(value in {"applied", "no_write", "not_applicable"} for value in statuses)
            else "unresolved"}


class _CoverageProvider:
    """Use the existing account; coverage calls are never another source intake."""
    def __init__(self, provider: Any, prefix: str):
        self._provider, self._prefix = provider, prefix

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def _inventory_call(self, operation: str, manifest: dict[str, Any], **kwargs: Any) -> Any:
        from harness_mem.autonomous.provider import source_coverage_inventory_enabled
        from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, _consumed

        original = getattr(self._provider, "timeout_seconds", None)
        selected = original
        inventory_stage = operation == "decide" or manifest.get("contract_version") == "candidate-semantic-verification-v2"
        if original == 300 and inventory_stage and source_coverage_inventory_enabled(manifest):
            # Complete-source inventory is larger than the normal four-point
            # Dream batch. Two real V5 attempts exhausted the default deadline.
            # Reuse the executor's existing 900s maximum within the *same*
            # remaining native-time reservation; caller-specific limits stay.
            owner = getattr(self._provider, "task_budget_binding", None)
            if owner is not None:
                account = read_task_budget_receipt(Path(owner.data_dir), owner.task_scope)
                windows = ((manifest.get("source_coverage") or {}).get("inventory_input") or {}).get("windows") or []
                if len(windows) > 4:
                    remaining = (account["bounds"]["max_seconds"] - _consumed(account)["seconds"]
                        if isinstance(account, dict) else owner.config.task_model_budget_max_seconds)
                    selected = max(original, min(900, int(remaining)))
        if selected != original:
            self._provider.timeout_seconds = selected
        try:
            return getattr(self._provider, operation)(manifest, **kwargs)
        finally:
            if selected != original:
                self._provider.timeout_seconds = original

    def decide(self, manifest: dict[str, Any], **kwargs: Any) -> Any:
        return self._inventory_call("decide", manifest, **kwargs)

    def verify(self, manifest: dict[str, Any], **kwargs: Any) -> Any:
        return self._inventory_call("verify", manifest, **kwargs)

    def bind_task_budget(self, binding: Any, *, phase: str, slice_id: str, retry_of: str | None = None) -> None:
        binder = getattr(self._provider, "bind_task_budget", None)
        if not callable(binder):
            raise ProviderError("source coverage requires the already bound budget owner", kind="setup_required")
        binder(binding, phase="dream", slice_id=f"{self._prefix}:{slice_id}", retry_of=retry_of)


async def run_applied_source_coverage(
    backend: Any, *, project_name: str, project_root: str | Path, run_id: str,
    checkpoint: dict[str, Any], notes: list[str], items: Sequence[Any], provider: Any,
    persist: Callable[[], Awaitable[None]],
    boundary: Callable[[], Awaitable[None]] | None = None,
    owner_heartbeat: Callable[[], None] | None = None,
    provider_failure: Callable[[ProviderError, Mapping[str, Any]], Awaitable[None]] | None = None,
    prepare_guard: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> bool:
    """Process at most one applied original group; receipt IDs do not alter its manifest."""
    ledger = checkpoint.setdefault("source_coverage", {})
    for item in items:
        if item.final_action != "applied" or item.result.get("truth_change") not in {"refine", "replace"}:
            continue
        key = str(item.source_id)
        state = ledger.get(key)
        if not _coverage_pending(state):
            continue
        prepared = None
        try:
            if state is not None and state.get("commit_bindings"):
                if await _recover_committed(backend, state, project_name=project_name,
                                            project_root=project_root):
                    await persist()
                    return True
            prepared = await _prepare(backend, project_name=project_name, project_root=project_root,
                                     run_id=run_id, item=item, checkpoint=checkpoint, notes=notes,
                                     include_current_comparison=True)
            if prepared is None:
                if state is not None:
                    raise ValueError("source_coverage_attempt_binding_changed")
                ledger[key] = {"status": "not_applicable", "predecessor_id": key,
                               "contract": CONTRACT}
                continue
            binding = prepared["binding"]
            if prepare_guard is not None:
                await prepare_guard(prepared)
            binding_hash = _digest(binding)
            state = _state_for_binding(state, binding)
            ledger[key] = state
            await persist()
            if boundary is not None:
                await boundary()
            loop = asyncio.get_running_loop()
            cancelled = threading.Event()

            def heartbeat() -> None:
                if cancelled.is_set():
                    raise ProviderError("source coverage cancelled", kind="transient")
                if owner_heartbeat is not None:
                    owner_heartbeat()

            def save(update: dict[str, Any]) -> None:
                async def commit() -> None:
                    copied = dict(update)
                    error = copied.pop("_provider_error", None)
                    if error is not None:
                        if not isinstance(error, ProviderError):
                            raise ValueError("source_coverage_failure_object_invalid")
                        if (set(copied) - {"_receipt", "status", "reason_code"}
                                or copied.get("status") != "failed"):
                            raise ValueError("source_coverage_failure_update_invalid")
                        if provider_failure is not None:
                            await provider_failure(error, prepared)
                    receipt = copied.pop("_receipt", None)
                    if error is not None and (not isinstance(receipt, dict)
                        or receipt.get("attempt_id") != binding_hash or receipt.get("phase") != "provider_failure"
                        or receipt.get("source_job_id") != prepared["job"].id
                        or receipt.get("budget_call_id") != (
                            getattr(provider, "_last_budget_call_id", None)
                            if error.attempt_results else None)):
                        raise ValueError("source_coverage_failure_receipt_changed")
                    if receipt is not None:
                        notes.append("dream source coverage receipt: " + json.dumps(receipt, sort_keys=True))
                    state.update(copied)
                    await persist()
                    if copied.get("status") == "candidates_verified" and boundary is not None:
                        await boundary()
                asyncio.run_coroutine_threadsafe(commit(), loop).result()

            from harness_mem.autonomous.worker import run_source_coverage_attempt
            wrapped = _CoverageProvider(provider, f"source-coverage:{run_id}:{binding_hash}")
            task = asyncio.create_task(asyncio.to_thread(
                run_source_coverage_attempt, backend, provider=wrapped,
                project_name=project_name, project_root=Path(project_root),
                prepared=prepared, attempt_id=binding_hash, state=state, save=save,
                heartbeat=heartbeat, runtime_dir=Path(backend.data_dir) / "autonomous" / "provider-runtime",
            ))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled.set()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=45)
                except Exception:
                    pass
                raise
            finally:
                binding_owner = getattr(provider, "task_budget_binding", None)
                binder = getattr(provider, "bind_task_budget", None)
                if binding_owner is not None and callable(binder):
                    binder(binding_owner, phase="dream",
                           slice_id=f"dream:{run_id}:{checkpoint['slice_count']}")
            await persist()
            return True
        except CanonicalTransactionPreconditionError:
            # The common transaction may have committed an earlier point. Keep
            # each such receipt and never replay it after the guard changed.
            if state is not None and state.get("commit_bindings"):
                await _recover_committed(backend, state, project_name=project_name,
                                         project_root=project_root)
            ledger[key] = {**(state or {}), "status": "failed", "predecessor_id": key,
                           "reason_code": "source_coverage_context_changed_before_commit"}
            await _workspace_status(backend, ledger[key])
            await persist()
            return True
        except ProviderError as exc:
            exc._source_coverage_provider_failure = True
            try:
                if provider_failure is not None and prepared is not None:
                    await provider_failure(exc, prepared)
                ledger[key] = {**(state or {}), "status": "failed", "predecessor_id": key,
                               "reason_code": exc.failure_reason or "source_coverage_provider_failed"}
                await _workspace_status(backend, ledger[key])
                await persist()
            except Exception as bookkeeping_error:
                code = str(bookkeeping_error)
                exc._source_coverage_bookkeeping_failure = (code
                    if isinstance(bookkeeping_error, ValueError) and 0 < len(code) <= 160
                    and all(char in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in code)
                    else type(bookkeeping_error).__name__)
                raise exc from bookkeeping_error
            raise
        except ValueError as exc:
            if state is not None and state.get("commit_bindings"):
                await _recover_committed(backend, state, project_name=project_name,
                                         project_root=project_root)
            ledger[key] = {**(state or {}), "status": "failed", "predecessor_id": key,
                           "reason_code": str(exc) if str(exc).startswith("source_coverage_") else "source_coverage_invalid_binding"}
            await _workspace_status(backend, ledger[key])
            await persist()
            return True
    return False


async def _recover_committed(backend: Any, state: dict[str, Any], *,
                             project_name: str, project_root: str | Path) -> bool:
    """A crash after SQLite commit must not execute another semantic mutation."""
    inventory_unresolved = False
    if "inventory_verification" in state:
        from harness_mem.autonomous.provider import source_coverage_audit_has_unresolved
        inventory_unresolved = source_coverage_audit_has_unresolved(state["inventory_verification"])
    store = backend.structured_store.knowledge_store
    commits = state.get("commit_bindings") or []
    committed = []
    for proof in commits:
        if (not proof.get("truth_ids") or len(proof["truth_ids"]) != len(proof.get("truth_sha256") or [])
                or not proof.get("decision_id") or not proof.get("candidate_id")):
            raise ValueError("source_coverage_commit_binding_incomplete")
        if not await store.current_change_committed(proof["decision_id"]):
            continue
        added = []
        for identity, digest in zip(proof["truth_ids"], proof["truth_sha256"]):
            entry = await store.get_entry(identity, project_name=project_name, project_root=project_root)
            if entry is None or _digest({"title": entry.title, "statement": entry.statement,
                                        "topic_path": entry.module_path}) != digest:
                raise ValueError("source_coverage_committed_readback_changed")
            added.append(entry)
        if any([await store.get_entry(identity, project_name=project_name, project_root=project_root)
                is not None for identity in proof["predecessor_ids"]]):
            raise ValueError("source_coverage_committed_predecessor_still_current")
        from harness_mem.commands.knowledge_assimilation import _verify_normal_search_after_truth_write
        await _verify_normal_search_after_truth_write(
            backend, project_name=project_name, project_root=Path(project_root),
            added_entries=added, predecessor_entries=[],
        )
        proof["status"] = "applied"
        committed.append(proof["candidate_id"])
    if not committed:
        return False
    pending = []
    unresolved = []
    statuses = []
    saved_outcomes = list(state.get("candidate_outcomes") or [])
    for identity in state.get("candidate_ids") or []:
        row = await store.get_candidate(identity)
        if row is None:
            raise ValueError("source_coverage_candidate_workspace_missing")
        if row.status == "pending":
            pending.append(identity)
        points = _refresh_candidate_outcomes(saved_outcomes, identity, row)
        handoff = any(point.get("disposition") == "handoff" for point in points)
        if row.status in {"pending", "deferred", "conflict", "rejected"} or handoff:
            unresolved.append(identity)
        statuses.extend(points)
    if pending:
        # A partial apply is closed conservatively. The remaining points are
        # not replayed with a different plan after another point changed scope.
        state.update(status="failed", reason_code="source_coverage_partial_commit",
                     committed_candidate_ids=committed)
    elif unresolved or inventory_unresolved:
        state.update(status="unresolved", reason_code=("source_coverage_inventory_audit_unresolved"
                     if inventory_unresolved else "source_coverage_partial_resolution"),
                     committed_candidate_ids=committed)
    else:
        state.update(status="applied", reason_code="source_coverage_commit_recovered",
                     committed_candidate_ids=committed)
    state["candidate_outcomes"] = statuses
    _refresh_outcome_counts(state, statuses, verified_commit_count=len(committed))
    return True


def _refresh_candidate_outcomes(saved: Sequence[Mapping[str, Any]], identity: str,
                                candidate: Any) -> list[dict[str, Any]]:
    """A candidate can have multiple independently important plan points."""
    points = [row for row in saved if row.get("candidate_id") == identity] or [{}]
    rows = []
    for point in points:
        disposition = point.get("disposition")
        planned = str(point.get("status") or "")
        if planned.startswith("planned_") and not disposition:
            disposition = planned[len("planned_"):]
        if point.get("handoff_id") or planned == "planned_handoff":
            disposition = "handoff"
        rows.append({**point, "candidate_id": identity,
            "status": candidate.status if candidate is not None else "missing",
            "candidate_sha256": _digest(candidate.to_dict()) if candidate is not None else None,
            **({"planned_disposition": planned[len("planned_"):]}
               if planned.startswith("planned_") else {}),
            **({"disposition": disposition} if disposition else {})})
    return rows


def _refresh_outcome_counts(state: dict[str, Any], rows: Sequence[Mapping[str, Any]], *,
                            verified_commit_count: int = 0) -> None:
    """Keep point dispositions separate from candidate lifecycle and writes."""
    existing = state.get("result_status_counts") or {}
    counts = {key: existing[key] for key in (
        "promoted", "confirmed", "no_write", "handoff", "deferred", "conflict", "rejected", "missing", "pending")
        if type(existing.get(key)) is int and existing[key] >= 0}
    dispositions = {str(row["disposition"]) for row in rows if row.get("disposition")}
    point_counts = {key: sum(row.get("disposition") == key for row in rows) for key in dispositions}
    # These are actual common-apply results. A planned handoff, including one
    # sharing a candidate already assimilated by an add, does not establish
    # TaskHandoff materialization. Keep its plan without inventing a count.
    # A planned add and an assimilated candidate are not a canonical write.
    # Only independently recovered commit proofs can augment this counter.
    if verified_commit_count:
        counts["promoted"] = max(counts.get("promoted", 0), verified_commit_count)
    state["result_status_counts"] = counts
    state["point_disposition_counts"] = point_counts
    unique = {row["candidate_id"]: row.get("status", "missing") for row in rows}
    state["candidate_status_counts"] = {status: sum(value == status for value in unique.values())
                                        for status in set(unique.values())}


async def _workspace_status(backend: Any, state: dict[str, Any]) -> None:
    """Retain actual pending/terminal status after a failed multi-point apply."""
    rows = []
    for identity in state.get("candidate_ids") or []:
        candidate = await backend.structured_store.knowledge_store.get_candidate(identity)
        rows.extend(_refresh_candidate_outcomes(state.get("candidate_outcomes") or [], identity, candidate))
    if rows:
        state["candidate_outcomes"] = rows
        _refresh_outcome_counts(state, rows)


def _terminal_fixed(run: Any) -> str:
    """Seal history, excluding only this owner's bounded side receipts."""
    payload = run.to_dict()
    checkpoint = dict(payload["continuation"])
    for key in ("source_coverage", "terminal_coverage_takeover", "terminal_coverage_receipts"):
        checkpoint.pop(key, None)
    return _digest({**payload, "continuation": checkpoint})


async def pending_terminal_source_coverage_count(
    backend: Any, *, project_name: str, exclude_run_id: str | None = None,
    origin_run_id: str | None = None,
) -> int:
    """Count finite old obligations before a new carrier freezes its bound."""
    total = 0
    for prior in await backend.structured_store.list_dream_runs(project_name, limit=8):
        if (prior.id == exclude_run_id or (origin_run_id is not None and prior.id != origin_run_id)
                or prior.status != "failed" or prior.completed_at is None
                or prior.trigger_source != "ide_hook"):
            continue
        applied = {item.source_id for item in prior.items if item.final_action == "applied"
                   and item.result.get("truth_change") in {"refine", "replace"}}
        ledger = prior.continuation.get("source_coverage") or {}
        total += sum(key in applied and _coverage_pending(ledger.get(key))
                     for key in set(prior.continuation.get("source_coverage_pending_ids") or []))
    return total


async def bound_terminal_source_coverage_origin(
    backend: Any, *, project_name: str, project_root: str | Path, config: Any,
    host_client: str, origin_run_id: str | None = None, require_idle: bool = True,
) -> tuple[Any, str, str, str]:
    """Read-only proof for the old task; never create a source or resume a run."""
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin

    require = _require_origin
    recent = await backend.structured_store.list_dream_runs(project_name, limit=8)
    if require_idle:
        require(not recent or recent[0].status != "continuing", "terminal_coverage_current_continuation_exists")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
        for active in backend.reflection_job_store.list(project_name=project_name, status="processing", kind="dream"):
            stamp = active.updated_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            require(stamp < cutoff, "terminal_coverage_processing_active")
    origin = item = None
    for prior in recent:
        if ((origin_run_id is not None and prior.id != origin_run_id) or prior.status != "failed"
                or prior.completed_at is None or prior.trigger_source != "ide_hook"):
            continue
        applied = {value.source_id: value for value in prior.items if value.final_action == "applied"
                   and value.result.get("truth_change") in {"refine", "replace"}}
        for key in prior.continuation.get("source_coverage_pending_ids") or []:
            state = (prior.continuation.get("source_coverage") or {}).get(key) or {}
            if not _coverage_pending(state):
                continue
            require(key in applied, "terminal_coverage_pending_item_missing")
            origin, item = prior, applied[key]
            break
        if origin is None and not require_idle and origin_run_id == prior.id:
            origin = prior  # An already claimed carrier may finish bookkeeping.
        if origin is not None:
            break
    require(origin is not None, "no_terminal_pending_coverage")
    _run, generation, trigger = await _bound_source_account(
        backend, run=origin, project_name=project_name, project_root=str(project_root),
        config=config, host_client=host_client, require_remaining=require_idle)
    cp = origin.continuation
    count, maximum = cp.get("slice_count"), cp.get("max_slices")
    initial = cp.get("terminal_source_coverage_initial_count", 0)
    takeover = cp.get("terminal_coverage_takeover") or {}
    extra, claims = takeover.get("slice_count", 0), takeover.get("claims", {})
    require(type(count) is int and type(maximum) is int and type(initial) is int and initial >= 0
            and maximum == len(cp.get("target_ids") or []) + 1 + 2 * initial
            and type(extra) is int and extra >= 0 and isinstance(claims, dict) and extra == len(claims)
            and 0 <= count and (count + extra < maximum if require_idle else count + extra <= maximum),
            "terminal_coverage_original_slices_exhausted")
    if takeover:
        require(takeover.get("contract") == TERMINAL_TAKEOVER_CONTRACT
                and takeover.get("origin_fixed_sha256") == _terminal_fixed(origin),
                "terminal_coverage_origin_binding_changed")
    prepared = (await _prepare(backend, project_name=project_name, project_root=project_root,
        run_id=origin.id, item=item, checkpoint=cp, notes=origin.notes or [])) if item is not None else None
    if prepared is not None:
        _assert_original_successors(origin, item, prepared)
        state = (cp.get("source_coverage") or {}).get(item.source_id) or {}
        if _interrupted_retryable(state):
            await _prove_interrupted_retry(backend, origin=origin, item=item, prepared=prepared,
                config=config, host_client=host_client, allow_active_owner=not require_idle)
        if _partial_retryable(state):
            await _prove_partial_retry(backend, origin=origin, item=item, prepared=prepared,
                config=config, host_client=host_client, allow_active_owner=not require_idle)
        if _zero_retryable(state):
            await _prove_zero_retry(backend, origin=origin, item=item, prepared=prepared,
                config=config, host_client=host_client, allow_active_owner=not require_idle)
        await _assert_partial_history(backend, state, prepared["binding"])
    prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
    source_jobs = {note[len(prefix):].strip() for note in origin.notes or [] for prefix in prefixes
                   if note.startswith(prefix)}
    require(len(source_jobs) == 1, "continuation_source_binding_missing")
    return origin, generation, trigger, next(iter(source_jobs))


async def _terminal_carrier(backend: Any, *, project_name: str, project_root: str | Path,
                            carrier_run_id: str, provider: Any, config: Any,
                            host_client: str, require_fresh_owner: bool = True,
                            failure_account: Callable[..., Awaitable[Any]] | None = None) -> Any:
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope

    require = _require_origin
    carrier = await backend.structured_store.get_dream_run(carrier_run_id)
    latest = await backend.structured_store.list_dream_runs(project_name, limit=1)
    require(carrier is not None and carrier.project_name == project_name
            and carrier.status == "processing" and carrier.trigger_source == "ide_hook"
            and bool(latest) and latest[0].id == carrier.id, "terminal_coverage_carrier_invalid")
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    require(reflection is not None and reflection.status == "processing" and reflection.kind == "dream"
            and reflection.source == "ide_hook" and reflection.project_name == project_name
            and Path(reflection.project_root).resolve() == Path(project_root).resolve(),
            "terminal_coverage_carrier_owner_invalid")
    updated = reflection.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
    if require_fresh_owner:
        require(updated >= stale_before, "terminal_coverage_carrier_owner_stale")
    for active in backend.reflection_job_store.list(project_name=project_name, status="processing", kind="dream"):
        timestamp = active.updated_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        require(active.id == reflection.id or timestamp < stale_before, "terminal_coverage_competing_owner")
    # A first slice has not appended its later Hook completion note yet.
    # Active reflection inputs must bind its actual completed native intake.
    source_ids = [identity for identity in reflection.input_refs
                  if backend.transcript_store.get_distill_job(identity) is not None]
    require(len(source_ids) == 1, "terminal_coverage_carrier_source_missing")
    bound_account = failure_account or _bound_source_account
    _run, generation, trigger = await bound_account(
        backend, run=carrier, project_name=project_name, project_root=str(project_root),
        config=config, host_client=host_client, source_job_id=source_ids[0], require_remaining=False)
    pinned_origin = (carrier.continuation.get("terminal_source_coverage_origin_run_id")
                     or carrier.continuation.get("terminal_report_origin_run_id"))
    if pinned_origin is not None:
        require(isinstance(pinned_origin, str) and pinned_origin in reflection.input_refs,
                "terminal_coverage_carrier_origin_missing")
        _origin = await backend.structured_store.get_dream_run(pinned_origin)
        require(_origin is not None and _origin.status == "failed" and _origin.completed_at is not None,
                "terminal_coverage_carrier_origin_invalid")
        _ignored, old_generation, old_trigger = await bound_account(
            backend, run=_origin, project_name=project_name, project_root=str(project_root),
            config=config, host_client=host_client, require_remaining=False)
        prefixes = ("Hook session distill succeeded: ", "Hook session distill verified: ")
        jobs = {note[len(prefix):].strip() for note in _origin.notes or [] for prefix in prefixes
                if note.startswith(prefix)}
        require(len(jobs) == 1, "terminal_coverage_carrier_origin_mismatch")
        old_job = next(iter(jobs))
        require((generation, trigger, source_ids[0]) == (old_generation, old_trigger, old_job),
                "terminal_coverage_carrier_origin_mismatch")
    binding = getattr(provider, "task_budget_binding", None)
    require(binding is not None and binding.task_scope == maintenance_task_scope(trigger, generation)
            and binding.host_client == host_client
            and Path(binding.data_dir).resolve() == Path(backend.data_dir).resolve()
            and binding.config.to_runtime_config() == config.to_runtime_config()
            and getattr(provider, "host_client", None) == host_client,
            "terminal_coverage_carrier_budget_mismatch")
    job = backend.transcript_store.get_distill_job(source_ids[0])
    require(job.completed_chunk_count == job.expected_chunk_count
            and job.structural_audit.get("coverage") == "complete"
            and job.structural_audit.get("expected_chunks") == job.expected_chunk_count
            and job.structural_audit.get("completed_chunks") == job.completed_chunk_count
            and (job.promotion_summary.get("readback") or {}).get("verified") is True
            and (job.promotion_summary.get("readback") or {}).get("source_revision") == job.source_revision
            and job.completion_disposition is not None,
            "terminal_coverage_carrier_source_incomplete")
    return carrier


def _original_final_output_bindings(origin: Any, source_id: str) -> list[dict[str, Any]]:
    """Select the exact historical or original-inventory final receipt owner."""
    expected = []
    for note in origin.notes or []:
        prefix = "dream verification receipt: "
        if not note.startswith(prefix):
            continue
        rows = []
        for row in json.loads(note[len(prefix):]).get("final_output_bindings") or []:
            owner = "dream:" + source_id
            if "report_preservation_inventory_sha256" in row:
                digest = row["report_preservation_inventory_sha256"]
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef" for char in digest)):
                    continue
                owner = str(uuid5(NAMESPACE_URL,
                    f"harness-mem:dream-candidate:{origin.id}:{source_id}"))
            if row.get("owner_candidate_id") == owner:
                rows.append(row)
        if rows:
            expected = rows
    return expected


def _assert_original_successors(origin: Any, item: Any, prepared: dict[str, Any]) -> None:
    """A current same-ID row must still be the original applied final output."""
    expected = []
    rows = _original_final_output_bindings(origin, item.source_id)
    expected = [(row.get("title_sha256"), row.get("statement_sha256")) for row in rows]
    actual = [(hashlib.sha256(entry.title.encode()).hexdigest(),
               hashlib.sha256(entry.statement.encode()).hexdigest())
              for entry in prepared["successor_entries"]]
    if not expected or actual != expected:
        raise ValueError("terminal_coverage_original_successor_changed")


def _carrier_heartbeat(backend: Any, carrier: Any, *, config: Any) -> Callable[[], None]:
    """Refresh the existing exact claim when the native provider already ticks."""
    from harness_mem.core.schemas.reflection_job import ReflectionJob

    store = backend.reflection_job_store
    first = store.get(carrier.reflection_job_id)
    if first is None:
        raise ValueError("terminal_coverage_carrier_owner_invalid")

    def identity(job: Any) -> str:
        body = job.to_dict()
        body.pop("updated_at", None)
        return _digest(body)

    expected = identity(first)
    refreshed = [None]
    mutex = threading.Lock()

    def heartbeat() -> None:
        with mutex:
            now = time.monotonic()
            if refreshed[0] is not None and now - refreshed[0] < 15:
                return
            with store._index.locked_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute("SELECT data FROM reflection_jobs WHERE id = ?", (first.id,)).fetchone()
                    current = ReflectionJob.from_dict(json.loads(row["data"])) if row is not None else None
                    if (current is None or current.status != "processing" or identity(current) != expected):
                        raise ProviderError("terminal coverage reflection claim changed", kind="unrecoverable",
                                            failure_reason="terminal_coverage_carrier_owner_changed")
                    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
                    rows = connection.execute("SELECT data FROM reflection_jobs WHERE project_name = ? AND kind = 'dream' AND status = 'processing'",
                                              (carrier.project_name,)).fetchall()
                    for record in rows:
                        active = ReflectionJob.from_dict(json.loads(record["data"]))
                        stamp = active.updated_at
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone.utc)
                        if active.id != first.id and stamp >= cutoff:
                            raise ProviderError("another reflection owns terminal coverage", kind="unrecoverable",
                                                failure_reason="terminal_coverage_competing_owner")
                    # Reuse the ReflectionJobStore owner under the same SQLite
                    # transaction; a changed/deleted/closed claim cannot revive.
                    store._save_locked(connection, current)
                except Exception:
                    connection.rollback()
                    raise
            refreshed[0] = now
    return heartbeat


async def run_pending_terminal_source_coverage(
    backend: Any, *, project_name: str, project_root: str | Path, carrier_run_id: str,
    provider: Any, config: Any, host_client: str,
    boundary: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Carry one unexecuted old obligation without resuming terminal traversal."""
    from types import SimpleNamespace
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.autonomous.executors.task_budget import bind_maintenance_task
    from harness_mem.autonomous.worker import autonomous_runtime_fingerprint

    require = _require_origin
    summary: dict[str, Any] = {"worked": False, "pending": False, "status": "skipped",
                               "reason": "no_terminal_pending_coverage"}
    try:
        carrier = await _terminal_carrier(
            backend, project_name=project_name, project_root=project_root,
            carrier_run_id=carrier_run_id, provider=provider, config=config, host_client=host_client)
        canonical = getattr(backend.structured_store, "_canonical", None)
        require(canonical is not None, "terminal_coverage_canonical_cas_required")
        carrier_raw = canonical.get_payload_json("dream_runs", carrier.id)
        require(carrier_raw is not None, "terminal_coverage_carrier_missing")
        require(_digest(json.loads(carrier_raw)) == _digest(carrier.to_dict()),
                "terminal_coverage_carrier_snapshot_changed")
        carrier_sha = hashlib.sha256(carrier_raw.encode()).hexdigest()
        ordinal = carrier.continuation.get("slice_count")
        require(type(ordinal) is int and ordinal > 0, "terminal_coverage_carrier_slice_invalid")
        carrier_key = f"{carrier.id}:{ordinal}"
        recent = await backend.structured_store.list_dream_runs(project_name, limit=8)
        pinned = carrier.continuation.get("terminal_source_coverage_origin_run_id")
        for prior in recent:
            claims = (prior.continuation.get("terminal_coverage_takeover") or {}).get("claims") or {}
            if carrier_key in claims:
                return {**summary, "reason": "carrier_slice_already_claimed", "origin_run_id": prior.id,
                        "pending": any(_coverage_pending(prior.continuation.get("source_coverage", {}).get(key))
                            for key in prior.continuation.get("source_coverage_pending_ids") or [])}
        origin = item = None
        for prior in recent:
            if (prior.id == carrier.id or (pinned is not None and prior.id != pinned)
                    or prior.status != "failed" or prior.completed_at is None
                    or prior.trigger_source != "ide_hook"):
                continue
            ledger = prior.continuation.get("source_coverage") or {}
            by_id = {value.source_id: value for value in prior.items if value.final_action == "applied"
                     and value.result.get("truth_change") in {"refine", "replace"}}
            for key in prior.continuation.get("source_coverage_pending_ids") or []:
                if not _coverage_pending(ledger.get(key)):
                    continue
                require(key in by_id, "terminal_coverage_pending_item_missing")
                origin, item = prior, by_id[key]
                break
            if origin is not None:
                break
        if origin is None:
            return summary
        summary.update(origin_run_id=origin.id, predecessor_id=item.source_id)
        old_raw = canonical.get_payload_json("dream_runs", origin.id)
        require(old_raw is not None and _digest(json.loads(old_raw)) == _digest(origin.to_dict()),
                "terminal_coverage_origin_snapshot_changed")
        expected_sha = hashlib.sha256(old_raw.encode()).hexdigest()
        _old, generation, trigger = await _bound_source_account(
            backend, run=origin, project_name=project_name, project_root=str(project_root),
            config=config, host_client=host_client)
        old_scope = origin.continuation
        count, maximum = old_scope.get("slice_count"), old_scope.get("max_slices")
        initial = old_scope.get("terminal_source_coverage_initial_count", 0)
        require(type(count) is int and type(maximum) is int and 0 <= count < maximum
                and type(initial) is int and initial >= 0
                and maximum == len(old_scope.get("target_ids") or []) + 1
                + 2 * initial,
                "terminal_coverage_original_slice_bound_invalid")
        takeover = old_scope.setdefault("terminal_coverage_takeover", {
            "contract": TERMINAL_TAKEOVER_CONTRACT, "slice_count": 0, "claims": {},
            "origin_fixed_sha256": _terminal_fixed(origin)})
        require(takeover.get("contract") == TERMINAL_TAKEOVER_CONTRACT
                and takeover.get("origin_fixed_sha256") == _terminal_fixed(origin),
                "terminal_coverage_origin_binding_changed")
        extra, claims = takeover.get("slice_count"), takeover.get("claims")
        require(type(extra) is int and extra >= 0 and isinstance(claims, dict) and extra == len(claims)
                and count + extra < maximum, "terminal_coverage_original_slices_exhausted")
        fixed, code = _terminal_fixed(origin), autonomous_runtime_fingerprint()
        prepared = await _prepare(backend, project_name=project_name, project_root=project_root,
            run_id=origin.id, item=item, checkpoint=old_scope, notes=origin.notes or [],
            include_current_comparison=True)
        if prepared is not None:
            _assert_original_successors(origin, item, prepared)
        source_binding = prepared["binding"] if prepared is not None else {"not_applicable": item.source_id}
        from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt
        # These accounts were fully checked above, before this claim can dispatch.
        # Failure bookkeeping may preserve a terminal error; it cannot dispatch.
        frozen_accounts: dict[str, Any] = {}
        frozen_sources: dict[str, Any] = {}
        for bound_run in (origin, carrier):
            scope = bound_run.continuation["maintenance_scope"]
            task = maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
            account = read_task_budget_receipt(Path(backend.data_dir), task)
            frozen_accounts[task] = json.loads(json.dumps(account))
            source_ids = {row["slice_id"][len("source-decide:"):] for row in account["calls"]
                          if row.get("phase") == "source" and str(row.get("slice_id", "")).startswith("source-decide:")}
            require(len(source_ids) == 1, "continuation_source_binding_missing")
            source_job = backend.transcript_store.get_distill_job(next(iter(source_ids)))
            revision, _rendered, _raw = _source_report_context(backend, project_name=project_name,
                source_id=source_job.source_id, source_revision=source_job.source_revision)
            frozen_sources[bound_run.id] = {"task": task, "scope": dict(scope), "job_id": source_job.id,
                "job_sha256": _digest(source_job.to_dict()), "revision_sha256": _digest(revision.model_dump(mode="json"))}
        failure: dict[str, Any] = {}

        async def failure_account(_backend: Any, *, run: Any, source_job_id: str | None = None,
                                  **_kwargs: Any) -> tuple[Any, str, str]:
            from harness_mem.autonomous.authorization import background_status
            from harness_mem.maintenance_lock import maintenance_is_locked

            require(isinstance(failure.get("error"), ProviderError), "source_coverage_failure_object_invalid")
            frozen = frozen_sources.get(run.id)
            require(frozen is not None and run.project_name == project_name
                and run.continuation.get("maintenance_scope") == frozen["scope"], "continuation_account_mismatch")
            auth = background_status(config, client=host_client)
            require(auth.ready and auth.selected_cli == host_client, "continuation_not_authorized")
            require(not maintenance_is_locked(backend.data_dir, trigger_id=trigger), "exclusive_maintenance_run_active")
            account = read_task_budget_receipt(Path(backend.data_dir), frozen["task"])
            before = frozen_accounts[frozen["task"]]
            require(isinstance(account, dict)
                and {k: v for k, v in account.items() if k != "calls"}
                    == {k: v for k, v in before.items() if k != "calls"}, "source_coverage_failure_account_changed")
            fields = ("max_calls", "max_seconds", "max_input_tokens", "max_output_tokens", "host_max_output_tokens")
            require(account.get("bounds") == {key: getattr(config, "task_model_budget_" + key) for key in fields},
                    "continuation_bounds_changed")
            calls = account.get("calls")
            require(isinstance(calls, list) and calls[:len(before["calls"])] == before["calls"],
                    "source_coverage_failure_account_prefix_changed")
            require(len({row.get("call_id") for row in calls}) == len(calls), "continuation_call_identity_invalid")
            additions = calls[len(before["calls"]):]
            for index, call in enumerate(additions):
                require(call.get("phase") == "dream" and isinstance(call.get("call_id"), str)
                    and str(call.get("slice_id", "")).startswith(f"source-coverage:{origin.id}:{_digest(source_binding)}:"),
                    "source_coverage_failure_call_scope_changed")
                if call.get("status") == "failed" and index == len(additions) - 1:
                    error = failure["error"]
                    require(index == len(additions) - 1 and call["call_id"] == failure.get("call_id")
                        and bool(error.attempt_results or error.native_attempts)
                        and call.get("reconciled_at") is not None,
                        "source_coverage_failure_terminal_unproved")
                else:
                    require(call.get("status") in {"completed", "failed"} and call.get("usage_exact") is True,
                            "continuation_usage_unknown_or_active")
                if call.get("usage_exact") is True:
                    usage = call.get("usage") or {}
                    require(all(type(usage.get(key)) in ((int, float) if key == "duration_seconds" else (int,))
                        and math.isfinite(usage[key]) and usage[key] >= 0
                        for key in ("input_tokens", "output_tokens", "duration_seconds")), "continuation_usage_invalid")
            require(source_job_id is None or source_job_id == frozen["job_id"], "continuation_source_binding_missing")
            job = backend.transcript_store.get_distill_job(frozen["job_id"])
            require(job is not None and _digest(job.to_dict()) == frozen["job_sha256"], "continuation_source_scope_mismatch")
            revision, _rendered, _raw = _source_report_context(backend, project_name=project_name,
                source_id=job.source_id, source_revision=job.source_revision)
            require(_digest(revision.model_dump(mode="json")) == frozen["revision_sha256"],
                    "continuation_source_scope_mismatch")
            proof = _terminal_failed_account_proof(account) if calls[-1].get("status") == "failed" else None
            return await _bound_source_account(backend, run=run, project_name=project_name,
                project_root=str(project_root), config=config, host_client=host_client,
                source_job_id=source_job_id, require_remaining=False,
                **({"failure_account": proof} if proof is not None else {}))

        async def provider_failed(error: ProviderError, attempted: Mapping[str, Any]) -> None:
            require(isinstance(error, ProviderError) and prepared is not None
                and _failure_context_digest(attempted) == _failure_context_digest(prepared),
                "source_coverage_failure_context_changed")
            if failure:
                require(failure["error"] is error, "source_coverage_failure_object_changed")
            else:
                failure.update(error=error, call_id=getattr(provider, "_last_budget_call_id", None))
            error._source_coverage_provider_failure = True
            await failure_account(backend, run=origin)
            claim["status"] = "failed"
        existing = old_scope.get("source_coverage", {}).get(item.source_id) or {}
        interrupted_proof = partial_proof = zero_proof = None
        if existing:
            interrupted = _interrupted_retryable(existing)
            partial = _partial_retryable(existing)
            zero = _zero_retryable(existing)
            if interrupted:
                require(prepared is not None, "source_coverage_interrupted_original_source_missing")
                interrupted_proof = await _prove_interrupted_retry(backend, origin=origin, item=item,
                    prepared=prepared, config=config, host_client=host_client,
                    active_carrier_id=carrier.id, allow_active_owner=True)
            if partial:
                require(prepared is not None, "source_coverage_partial_original_source_missing")
                partial_proof = await _prove_partial_retry(backend, origin=origin, item=item,
                    prepared=prepared, config=config, host_client=host_client,
                    active_carrier_id=carrier.id, allow_active_owner=True)
            if zero:
                require(prepared is not None, "source_coverage_zero_original_source_missing")
                zero_proof = await _prove_zero_retry(backend, origin=origin, item=item,
                    prepared=prepared, config=config, host_client=host_client,
                    active_carrier_id=carrier.id, allow_active_owner=True)
            await _assert_partial_history(backend, existing, source_binding)
            for previous in existing.get("previous_contract_attempts") or []:
                proof = previous.get("partial_revalidation")
                if proof is not None:
                    partial_proof = proof
            retry = _contract_retryable(existing) or interrupted or partial or zero
            # Prove that only the semantic contract changed before adopting a
            # prior no-write. No source, successor or completed job drift passes.
            if retry:
                _state_for_binding(existing, source_binding, interrupted_proof=interrupted_proof,
                    partial_proof=partial_proof, zero_proof=zero_proof)
            require(retry or (existing.get("terminal_takeover_contract") == TERMINAL_TAKEOVER_CONTRACT
                    and existing.get("binding") == source_binding),
                    "terminal_coverage_prior_attempt_not_adoptable")
            historical = {row.get("binding_sha256") for row in existing.get("previous_contract_attempts") or []
                          if row.get("contract") == _PREVIOUS_CONTRACT
                          or (row.get("contract") == _INTERRUPTED_CONTRACT
                              and (row.get("interrupted_adoption") or {}).get("contract")
                              == "source-coverage-interrupted-v2-adoption-v1")
                          or (row.get("contract") == _PARTIAL_CONTRACT
                              and (row.get("partial_revalidation") or {}).get("contract")
                              == "source-coverage-partial-v3-revalidation-v1")}
            historical.update(row.get("binding_sha256") for row in existing.get("previous_contract_attempts") or []
                if row.get("contract") == _ZERO_CONTRACT and (row.get("zero_revalidation") or {}).get("contract")
                == "source-coverage-zero-v4-revalidation-v1")
            if retry:
                historical.add(existing["binding_sha256"])
            historical.discard(None)
            require(all(receipt.get("source_binding_sha256") in historical
                        or (receipt.get("runtime_fingerprint") == code
                            and receipt.get("source_binding_sha256") == _digest(source_binding))
                        for receipt in claims.values() if receipt.get("predecessor_id") == item.source_id),
                    "terminal_coverage_attempt_binding_changed")
        claim = {"origin_run_id": origin.id, "predecessor_id": item.source_id,
                 "origin_fixed_sha256": fixed, "source_binding_sha256": _digest(source_binding),
                 "runtime_fingerprint": code, "carrier_run_id": carrier.id,
                 "carrier_reflection_id": carrier.reflection_job_id,
                 "carrier_payload_sha256": carrier_sha, "status": "claimed"}
        if interrupted_proof is not None or zero_proof is not None or (existing and _partial_retryable(existing)):
            old_scope["source_coverage"][item.source_id] = _state_for_binding(
                existing, source_binding, interrupted_proof=interrupted_proof,
                partial_proof=partial_proof, zero_proof=zero_proof)
        claims[carrier_key] = claim
        takeover["slice_count"] = extra + 1
        local_notes = list(origin.notes or [])
        note_count = len(local_notes)
        old_receipts = list(old_scope.get("terminal_coverage_receipts") or [])
        saved_binding = getattr(provider, "task_budget_binding", None)
        saved_phase = getattr(provider, "_budget_phase", None)
        saved_slice = getattr(provider, "_budget_slice", None)
        saved_retry = getattr(provider, "_budget_retry_of", None)
        saved_last_call = getattr(provider, "_last_budget_call_id", None)
        require(saved_phase == "dream" and saved_slice == f"dream:{carrier.id}:{ordinal}",
                "terminal_coverage_carrier_phase_mismatch")
        saved_adapters = {"input_capability": getattr(provider, "_input_capability", None),
                          "output_limit_surface": getattr(provider, "_output_surface", None),
                          "explicit_fake_transport": getattr(provider, "_explicit_fake_transport", None)}
        carrier_provider = SimpleNamespace(task_budget_binding=saved_binding, host_client=host_client)

        async def persist() -> None:
            nonlocal expected_sha
            if interrupted_proof is not None:
                await _assert_interrupted_candidates(backend, interrupted_proof)
            if partial_proof is not None:
                await _assert_partial_snapshot(backend, partial_proof)
            require(_terminal_fixed(origin) == fixed, "terminal_coverage_historical_execution_changed")
            require(autonomous_runtime_fingerprint() == code, "terminal_coverage_runtime_changed")
            state = old_scope.get("source_coverage", {}).get(item.source_id)
            if state is not None:
                state["terminal_takeover_contract"] = TERMINAL_TAKEOVER_CONTRACT
            if len(local_notes) > note_count:
                old_scope["terminal_coverage_receipts"] = old_receipts + local_notes[note_count:]
            await _terminal_carrier(
                backend, project_name=project_name, project_root=project_root,
                carrier_run_id=carrier.id, provider=carrier_provider, config=config, host_client=host_client,
                require_fresh_owner=False,
                **({"failure_account": failure_account} if failure else {}))
            if failure:
                current_context = await _prepare(backend, project_name=project_name, project_root=project_root,
                    run_id=origin.id, item=item, checkpoint=old_scope, notes=origin.notes or [],
                    include_current_comparison=True)
                require(current_context is not None and _failure_context_digest(current_context)
                    == _failure_context_digest(prepared), "source_coverage_failure_context_changed")
            payload = origin.to_dict()
            mutations = [{"operation": "assert", "collection": "dream_runs", "entity_id": carrier.id,
                "project_name": project_name, "expected_sha256": carrier_sha},
                {"operation": "upsert", "collection": "dream_runs", "entity_id": origin.id,
                 "payload": payload, "expected_sha256": expected_sha}]
            if partial_proof is not None:
                for retained in partial_proof["committed_truth"]:
                    mutations.append({"operation": "assert", "collection": "knowledge_entries",
                        "entity_id": retained["entry_id"], "project_name": project_name,
                        "expected_sha256": retained["payload_sha256"]})
                    mutations.extend({"operation": "assert", "collection": "knowledge_sources",
                        "entity_id": source["source_id"], "project_name": project_name,
                        "expected_sha256": source["payload_sha256"]}
                        for source in retained["sources"])
                mutations.extend({"operation": "assert", "collection": "task_handoffs",
                    "entity_id": row["handoff_id"], "project_name": project_name,
                    "expected_sha256": row["handoff_sha256"]}
                    for row in partial_proof["deferred"])
            expected_sha = await _persist_terminal_source_checkpoint(
                backend, origin=origin, expected_sha=expected_sha, mutations=mutations)

        await persist()  # Consume the original finite slice before any CLI call.
        original_binding = bind_maintenance_task(data_dir=Path(backend.data_dir), host_client=host_client,
            config=config, trigger_id=trigger, dispatch_generation=generation)
        binder = getattr(provider, "bind_task_budget", None)
        require(callable(binder), "terminal_coverage_provider_binding_missing")
        owner_heartbeat = _carrier_heartbeat(backend, carrier, config=config)
        try:
            binder(original_binding, phase="dream", slice_id=f"source-coverage:{origin.id}:{count + extra + 1}")
            if prepared is None:
                old_scope.setdefault("source_coverage", {})[item.source_id] = {
                    "status": "not_applicable", "predecessor_id": item.source_id, "contract": CONTRACT}
                worked = True
            else:
                worked = await run_applied_source_coverage(
                    backend, project_name=project_name, project_root=project_root, run_id=origin.id,
                    checkpoint=old_scope, notes=local_notes, items=[item], provider=provider,
                    persist=persist, boundary=boundary, owner_heartbeat=owner_heartbeat,
                    provider_failure=provider_failed)
            claim["status"] = (old_scope.get("source_coverage", {}).get(item.source_id) or {}).get("status", "pending")
            await persist()
        finally:
            binder(saved_binding, phase=saved_phase, slice_id=saved_slice, retry_of=saved_retry, **saved_adapters)
            if hasattr(provider, "_last_budget_call_id"):
                provider._last_budget_call_id = saved_last_call
        state = old_scope.get("source_coverage", {}).get(item.source_id) or {}
        pending = any(_coverage_pending(old_scope.get("source_coverage", {}).get(key))
                      for key in old_scope.get("source_coverage_pending_ids") or [])
        return {**summary, "worked": worked, "pending": pending,
                "status": state.get("status", "pending"), "reason": state.get("reason_code"),
                "task_scope": original_binding.task_scope}
    except (ValueError, CanonicalTransactionPreconditionError, ProviderError) as exc:
        if isinstance(exc, ProviderError) and getattr(exc, "_source_coverage_provider_failure", False):
            raise
        if isinstance(exc, CanonicalTransactionPreconditionError):
            reason = "terminal_coverage_checkpoint_changed"
        elif isinstance(exc, ProviderError):
            reason = exc.failure_reason or "terminal_coverage_provider_failed"
        else:
            value = str(exc)
            reason = value if value.startswith(("terminal_coverage_", "continuation_", "source_coverage_",
                                                "source_report_", "exclusive_maintenance_")) else "terminal_coverage_invalid_binding"
        return {**summary, "status": "blocked", "reason": reason, "pending": False}


async def _failed_source_child_binding(
    backend: Any, *, project_name: str, project_root: str | Path, config: Any,
    host_client: str, child_run_id: str,
) -> dict[str, Any]:
    """Read-only proof for one previously failed native call; never permits inference."""
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt

    require = _require_origin
    child = await backend.structured_store.get_dream_run(child_run_id)
    latest = await backend.structured_store.list_dream_runs(project_name, limit=1)
    require(child is not None and child.project_name == project_name and child.status == "continuing"
        and child.trigger_source == "ide_hook" and latest and latest[0].id == child.id,
        "source_coverage_failure_child_not_current")
    cp = child.continuation
    pin = cp.get("terminal_source_coverage_origin_run_id")
    require(isinstance(pin, str) and not cp.get("terminal_report_origin_run_id"),
            "source_coverage_failure_child_origin_changed")
    origin = await backend.structured_store.get_dream_run(pin)
    require(origin is not None and origin.project_name == project_name and origin.status == "failed"
        and origin.completed_at is not None and origin.trigger_source == "ide_hook"
        and cp.get("maintenance_scope") == origin.continuation.get("maintenance_scope"),
        "source_coverage_failure_child_origin_changed")
    scope = cp.get("maintenance_scope") or {}
    task = maintenance_task_scope(scope.get("trigger_id"), scope.get("dispatch_generation"))
    account = read_task_budget_receipt(Path(backend.data_dir), task)
    require(isinstance(account, dict), "continuation_account_missing")
    proof = _terminal_failed_account_proof(account)
    _old, generation, trigger = await _bound_source_account(backend, run=origin,
        project_name=project_name, project_root=str(project_root), config=config, host_client=host_client,
        require_remaining=False, failure_account=proof)
    await _bound_source_account(backend, run=child, project_name=project_name,
        project_root=str(project_root), config=config, host_client=host_client,
        require_remaining=False, failure_account=proof)
    ordinal, maximum = cp.get("slice_count"), cp.get("max_slices")
    require(type(ordinal) is int and type(maximum) is int and 0 < ordinal <= maximum,
            "source_coverage_failure_child_slice_changed")
    original = origin.continuation
    count, bound, initial = original.get("slice_count"), original.get("max_slices"), original.get("terminal_source_coverage_initial_count", 0)
    takeover = original.get("terminal_coverage_takeover") or {}
    claims, extra = takeover.get("claims"), takeover.get("slice_count")
    require(type(count) is int and type(bound) is int and type(initial) is int and initial >= 0
        and bound == len(original.get("target_ids") or []) + 1 + 2 * initial
        and isinstance(claims, dict) and type(extra) is int and extra == len(claims)
        and 0 <= count and count + extra <= bound
        and takeover.get("contract") == TERMINAL_TAKEOVER_CONTRACT
        and takeover.get("origin_fixed_sha256") == _terminal_fixed(origin),
        "source_coverage_failure_original_slice_changed")
    claim_key = f"{child.id}:{ordinal}"
    claim = claims.get(claim_key)
    require(isinstance(claim, dict) and claim.get("carrier_run_id") == child.id
        and claim.get("carrier_reflection_id") == child.reflection_job_id
        and claim.get("origin_run_id") == origin.id and claim.get("origin_fixed_sha256") == _terminal_fixed(origin)
        and claim.get("status") in {"claimed", "extracting"}, "source_coverage_failure_claim_changed")
    key = claim.get("predecessor_id")
    state = (original.get("source_coverage") or {}).get(key)
    require(key in (original.get("source_coverage_pending_ids") or []) and isinstance(state, dict)
        and state.get("status") == "extracting" and not state.get("candidate_ids") and not state.get("commit_bindings")
        and state.get("terminal_takeover_contract") == TERMINAL_TAKEOVER_CONTRACT,
        "source_coverage_failure_state_changed")
    item = next((row for row in origin.items if row.source_id == key and row.final_action == "applied"
                 and row.result.get("truth_change") in {"refine", "replace"}), None)
    require(item is not None, "terminal_coverage_pending_item_missing")
    prepared = await _prepare(backend, project_name=project_name, project_root=project_root,
        run_id=origin.id, item=item, checkpoint=original, notes=origin.notes or [], include_current_comparison=True)
    require(prepared is not None and state.get("binding") == prepared["binding"]
        and state.get("binding_sha256") == _digest(prepared["binding"]) == claim.get("source_binding_sha256"),
        "source_coverage_failure_context_changed")
    _assert_original_successors(origin, item, prepared)
    failed = account["calls"][-1]
    require(failed.get("phase") == "dream" and failed.get("slice_id")
        == f"source-coverage:{origin.id}:{state['binding_sha256']}:source-decide:{prepared['job'].id}",
        "source_coverage_failure_call_scope_changed")
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    source_jobs = {row["slice_id"][len("source-decide:"):] for row in account["calls"][:-1]
                   if row.get("phase") == "source" and str(row.get("slice_id", "")).startswith("source-decide:")}
    reflection_jobs = {identity for identity in reflection.input_refs
                       if backend.transcript_store.get_distill_job(identity) is not None} if reflection else set()
    require(reflection is not None and reflection.status == "retryable" and reflection.phase == "metabolism"
        and reflection.lease_owner is None and reflection.lease_until is None and reflection.completed_at is None
        and reflection.project_name == project_name and reflection.kind == "dream" and reflection.source == "ide_hook"
        and Path(reflection.project_root).resolve() == Path(project_root).resolve()
        and origin.id in reflection.input_refs
        and len(source_jobs) == 1 and reflection_jobs == source_jobs,
        "source_coverage_failure_reflection_changed")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, config.dream_auto_max_runtime_seconds))
    for active in backend.reflection_job_store.list(project_name=project_name, status="processing", kind="dream"):
        stamp = active.updated_at if active.updated_at.tzinfo else active.updated_at.replace(tzinfo=timezone.utc)
        require(stamp < cutoff, "continuation_processing_active")
    canonical = backend.structured_store._canonical
    before = {run.id: canonical.get_payload_json("dream_runs", run.id) for run in (origin, child)}
    require(all(raw is not None and _digest(json.loads(raw)) == _digest(run.to_dict())
        for run in (origin, child) for raw in [before[run.id]]), "terminal_coverage_origin_snapshot_changed")
    receipt_prefix = "dream source coverage receipt: "
    receipts = [json.loads(row[len(receipt_prefix):]) for row in original.get("terminal_coverage_receipts") or []
                if row.startswith(receipt_prefix)]
    captured = any(row.get("phase") == "provider_failure" and row.get("attempt_id") == state["binding_sha256"]
        and row.get("budget_call_id") == failed["call_id"] for row in receipts)
    return {"origin": origin, "child": child, "generation": generation, "trigger": trigger,
        "account": account, "proof": proof, "prepared": prepared, "claim_key": claim_key,
        "key": key, "before": before, "reflection": reflection.to_dict(), "receipt_captured": captured}


async def bound_failed_source_child(backend: Any, *, project_name: str, project_root: str | Path,
    config: Any, host_client: str, child_run_id: str) -> tuple[Any, str, str]:
    binding = await _failed_source_child_binding(backend, project_name=project_name, project_root=project_root,
        config=config, host_client=host_client, child_run_id=child_run_id)
    return binding["child"], binding["generation"], binding["trigger"]


async def close_failed_source_child(backend: Any, *, project_name: str, project_root: str | Path,
    config: Any, host_client: str, child_run_id: str, generation: str, trigger_id: str) -> dict[str, Any]:
    """Close a known old failure without inventing its missing ProviderError or usage."""
    from harness_mem.autonomous.worker import autonomous_runtime_fingerprint
    from harness_mem.commands.dream_continuation import _bound_source_account, _require_origin
    from harness_mem.hook_background import background_generation_from_env, heartbeat_background_worker
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt

    require = _require_origin
    require(os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1"
        and background_generation_from_env() == generation, "continuation_detached_owner_required")
    ordinary = await backend.structured_store.get_dream_run(child_run_id)
    require(ordinary is not None, "source_coverage_failure_child_not_current")
    scope = ordinary.continuation.get("maintenance_scope") or {}
    current = read_task_budget_receipt(Path(backend.data_dir), maintenance_task_scope(
        scope.get("trigger_id"), scope.get("dispatch_generation")))
    if isinstance(current, dict) and current.get("calls") and all(
        row.get("status") == "completed" and row.get("usage_exact") is True for row in current["calls"]):
        await _bound_source_account(backend, run=ordinary, project_name=project_name,
            project_root=str(project_root), config=config, host_client=host_client,
            generation=generation, trigger_id=trigger_id, require_remaining=False)
        return {}
    binding = await _failed_source_child_binding(backend, project_name=project_name, project_root=project_root,
        config=config, host_client=host_client, child_run_id=child_run_id)
    require((binding["generation"], binding["trigger"]) == (generation, trigger_id), "continuation_pointer_mismatch")
    require(heartbeat_background_worker(Path(backend.data_dir), project_root=Path(project_root), client=host_client),
            "background_worker_lease_lost")
    origin, child = binding["origin"], binding["child"]
    account_sha = binding["proof"]["ledger_sha256"]
    closure = {"reason": "source_coverage_terminal_native_failure",
        "native_receipt_status": "captured" if binding["receipt_captured"] else "original_provider_receipt_missing",
        "account_binding_sha256": account_sha, "failed_call_id": binding["proof"]["failed_call_id"],
        "failed_call_sha256": binding["proof"]["failed_call_sha256"],
        "source_binding_sha256": _digest(binding["prepared"]["binding"]),
        "context_sha256": _failure_context_digest(binding["prepared"]),
        "runtime_fingerprint": autonomous_runtime_fingerprint(),
        "usage_status": "known" if binding["account"]["calls"][-1]["usage_exact"] else "unknown"}
    state = origin.continuation["source_coverage"][binding["key"]]
    state.update(status="failed", reason_code=closure["native_receipt_status"], failure_bookkeeping=closure)
    origin.continuation["terminal_coverage_takeover"]["claims"][binding["claim_key"]]["status"] = "failed"
    child.status, child.execution_status, child.resolution_status = "failed", "failed", "unresolved"
    child.completed_at = datetime.now(timezone.utc)
    child.continuation = {**child.continuation, "source_coverage_failure": closure,
        "execution_status": "failed", "resolution_status": "unresolved"}
    latest = await _failed_source_child_binding(backend, project_name=project_name, project_root=project_root,
        config=config, host_client=host_client, child_run_id=child_run_id)
    require(latest["before"] == binding["before"] and latest["reflection"] == binding["reflection"]
        and _failure_context_digest(latest["prepared"]) == closure["context_sha256"],
        "source_coverage_failure_context_changed")
    require(_digest(read_task_budget_receipt(Path(backend.data_dir), binding["account"]["task_scope"])) == account_sha,
            "source_coverage_failure_account_changed")
    require(autonomous_runtime_fingerprint() == closure["runtime_fingerprint"], "terminal_coverage_runtime_changed")
    mutations = [{"operation": "upsert", "collection": "dream_runs", "entity_id": run.id,
        "payload": run.to_dict(), "expected_sha256": hashlib.sha256(binding["before"][run.id].encode()).hexdigest()}
        for run in (origin, child)]
    await _persist_terminal_source_checkpoint(backend, origin=origin,
        expected_sha=hashlib.sha256(binding["before"][origin.id].encode()).hexdigest(),
        mutations=mutations, terminal_child=child)
    return {"run_id": child.id, "status": "failed", "execution_status": "failed", "resolution_status": "unresolved",
        "reason": closure["reason"], "source_coverage_failure": closure}
