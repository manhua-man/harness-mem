"""Resume a failed explicit source inventory without replaying its writes.

Only canonical Dream checkpoints, the original transcript ledger and the
existing candidate workspace supply inputs. Diagnostic files are not read.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from harness_mem.autonomous.models import SourceCoverageAuditPoint, SourceCoverageWindow
from harness_mem.autonomous.executors.task_budget import maintenance_task_scope, read_task_budget_receipt
from harness_mem.commands import dream_source_coverage as coverage
from harness_mem.core.schemas.dream_run import DreamItem


CONTRACT = "explicit-dream-source-audit-v1"
RESIDUAL_CONTRACT = "source-coverage-residual-audit-v1"
_TERMINAL = {"applied", "no_write", "unresolved", "failed", "not_applicable"}
_BUDGET_EXHAUSTION = {"input_budget_exhausted": "input_tokens", "output_budget_exhausted": "output_tokens",
                      "call_budget_exhausted": "calls", "time_budget_exhausted": "seconds"}


def _require(value: Any, reason: str) -> None:
    if not value:
        raise ValueError("source_coverage_audit_" + reason)


def _digest(value: Any) -> str:
    return coverage._digest(value)


def _raw_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source_ledger(origin: Any) -> dict:
    frozen = (origin.continuation.get("explicit_repair_scope") or {}).get("source") or {}
    key = "source_inventory_audit" if frozen.get("contract") == CONTRACT else "repair_source_coverage"
    return origin.continuation.get(key) or {}


async def _origin(backend: Any, *, project_name: str, project_root: str | Path,
                  origin_run_id: str, run_id: str, predecessor_ids: Sequence[str]) -> tuple[Any, dict, dict]:
    origin = await backend.structured_store.get_dream_run(origin_run_id)
    _require(origin is not None and origin.id != run_id and origin.project_name == project_name
             and origin.status == "failed" and origin.completed_at is not None
             and origin.trigger_source == "agent", "origin_invalid")
    outer = origin.continuation.get("explicit_repair_scope") or {}
    frozen = outer.get("source") or {}
    ledger = _source_ledger(origin)
    _require(frozen.get("contract") in {coverage.EXPLICIT_REPAIR_CONTRACT, CONTRACT}
             and frozen.get("run_id") == origin.id and frozen.get("project_name") == project_name
             and frozen.get("project_root_sha256") == _digest(str(Path(project_root).resolve()))
             and ledger.get("manifest_sha256") == _digest(frozen)
             and ledger.get("contract") == frozen.get("contract"),
             "origin_manifest_invalid")
    keys = list(predecessor_ids)
    _require(not isinstance(predecessor_ids, str) and bool(keys) and all(isinstance(key, str) and key for key in keys)
             and len(keys) == len(set(keys))
             and set(keys) <= set(frozen.get("source_bindings") or {}), "selection_invalid")
    for key in keys:
        state = (ledger.get("source_coverage") or {}).get(key) or {}
        binding = state.get("binding") or {}
        budget_failed = state.get("status") == "failed" and state.get("reason_code") in _BUDGET_EXHAUSTION
        _require((budget_failed or ((state.get("status") == "unresolved" or (
                    state.get("status") == "failed" and isinstance(state.get("inventory_observation"), dict)))
             and state.get("reason_code") == "source_coverage_inventory_audit_unresolved"))
                 and binding.get("contract") == coverage.CONTRACT
                 and binding.get("run_id") == origin.id and binding.get("predecessor_id") == key
                 and state.get("binding_sha256") == _digest(binding)
                 and binding == frozen["source_bindings"][key].get("binding"), "origin_state_invalid")
    raw = backend.structured_store._canonical.get_payload_json("dream_runs", origin.id)
    _require(raw is not None and _digest(json.loads(raw)) == _digest(origin.to_dict()), "origin_changed")
    account = read_task_budget_receipt(Path(backend.data_dir), ledger.get("task_scope", ""))
    maintenance = origin.continuation.get("maintenance_scope") or {}
    _require(isinstance(account, dict) and account.get("task_scope") == ledger.get("task_scope")
             and ledger.get("task_scope") == maintenance_task_scope(
                 maintenance.get("trigger_id", ""), maintenance.get("dispatch_generation", ""))
             and account.get("host_client") == frozen.get("host_client")
             and isinstance(account.get("calls"), list) and bool(account["calls"]), "account_missing")
    if frozen["contract"] == CONTRACT:
        count = frozen.get("account_prefix_count")
        _require(type(count) is int and 0 < count <= len(account["calls"])
                 and frozen.get("task_scope") == account["task_scope"]
                 and _digest(account["calls"][:count]) == frozen.get("account_prefix_sha256"),
                 "ancestor_account_changed")
    for key in keys:
        state = ledger["source_coverage"][key]
        if state.get("status") == "failed" and state.get("reason_code") in _BUDGET_EXHAUSTION:
            _budget_interruption(origin, state, frozen, account)
        elif state.get("status") == "failed":
            _validate_observation_witness(origin.to_dict(), key, account)
    return origin, frozen, account


def _budget_interruption(origin: Any, state: Mapping[str, Any], frozen: Mapping[str, Any],
                         account: dict) -> dict:
    """Prove a closed, pre-dispatch refusal without manufacturing a failed native call."""
    from harness_mem.autonomous.executors.task_budget import (
        _closed_allowance_calls, _consumed, effective_task_budget_bounds,
    )
    continuation = origin.continuation
    _require(isinstance(account, dict) and isinstance(account.get("calls"), list), "budget_account_missing")
    snapshot = continuation.get("task_budget") or {}
    reason = state.get("reason_code")
    failure = continuation.get("source_coverage_failure") or {}
    _require(frozen.get("contract") == CONTRACT and reason in _BUDGET_EXHAUSTION
             and continuation.get("failure_reason") == failure.get("failure_reason") == reason
             and snapshot.get("dispatch_failure_reason") == reason
             and snapshot.get("native_dispatch") == "refused_before_transport"
             and snapshot.get("unknown_calls") == 0
             and snapshot.get("task_scope") == account.get("task_scope")
             and snapshot.get("host_client") == account.get("host_client")
             and not state.get("commit_bindings") and not state.get("committed_candidate_ids")
             and not state.get("result_status_counts") and not state.get("point_disposition_counts"),
             "budget_refusal_unproved")
    _closed_allowance_calls(account["calls"])
    current_bounds = effective_task_budget_bounds(account)
    count = snapshot.get("reserved_calls")
    _require(type(count) is int and 0 < count <= len(account["calls"]), "budget_prefix_missing")
    prefix = account["calls"][:count]
    known = [{**{name: call.get(name) for name in ("call_id", "phase", "slice_id", "status", "usage")},
              "model_completion": call.get("model_completion") is True} for call in prefix]
    grants = snapshot.get("allowance_grants") or []
    _require(snapshot.get("known_usage") == known and snapshot.get("original_bounds") == account.get("bounds")
             and isinstance(grants, list) and account.get("allowance_grants", [])[:len(grants)] == grants,
             "budget_account_history_changed")
    previous = {**account, "calls": prefix, "allowance_grants": grants}
    bounds = effective_task_budget_bounds(previous)
    key = _BUDGET_EXHAUSTION[reason]
    field = {"calls": "max_calls", "seconds": "max_seconds", "input_tokens": "max_input_tokens",
             "output_tokens": "max_output_tokens"}[key]
    _require(bounds == snapshot.get("effective_bounds") and _consumed(previous)[key] >= bounds[field]
             and current_bounds[field] > bounds[field], "budget_exhaustion_or_allowance_unproved")
    prefix_text = "dream source coverage receipt: "
    failures = [json.loads(note[len(prefix_text):]) for note in [*origin.notes,
        *(continuation.get("terminal_coverage_receipts") or [])]
        if isinstance(note, str) and note.startswith(prefix_text)
        and json.loads(note[len(prefix_text):]).get("phase") == "provider_failure"]
    # Older broken bookkeeping omitted this ticket. Repaired bookkeeping retains
    # a refusal with no native attempt; it must never inherit a previous paid ID.
    _require(not failures or all(row == failures[0] for row in failures), "budget_refusal_receipt_conflict")
    if failures:
        ticket = failures[0]
        _require(set(ticket) == {"attempt_id", "phase", "source_job_id", "failure_kind", "failure_reason",
            "exit_code", "budget_call_id", "attempt_results", "native_attempts", "unknown_attempt_count"}
            and ticket["attempt_id"] == state["binding_sha256"]
            and ticket["source_job_id"] == state["binding"]["source_job_id"]
            and ticket["failure_kind"] == failure.get("kind") and ticket["failure_reason"] == reason
            and ticket["exit_code"] is None and ticket["budget_call_id"] is None
            and ticket["attempt_results"] == ticket["native_attempts"] == []
            and type(ticket["unknown_attempt_count"]) is int and ticket["unknown_attempt_count"] == 0,
            "budget_refusal_receipt_unproved")
    receipts = _observation_receipts(origin.to_dict(), state)
    phases = {row.get("phase"): row for row in receipts if row.get("phase") != "provider_failure"}
    slices = {"decide": "source-decide:" + state["binding"]["source_job_id"],
              "candidate_verify": "source-verify", "assimilate": "source-assimilate"}
    _require(set(phases) == set(slices), "budget_native_phases_unproved")
    call_prefix = f"source-coverage:{origin.id}:{state['binding_sha256']}:"
    selected = [call for call in prefix if str(call.get("slice_id", "")).startswith(call_prefix)]
    _require(len(selected) == len(slices), "budget_native_call_count_changed")
    for phase, suffix in slices.items():
        receipt = phases[phase]
        calls = [call for call in selected if call.get("slice_id") == call_prefix + suffix]
        attempts = receipt.get("native_attempts") or []
        _require(len(calls) == len(attempts) == 1 and calls[0].get("status") == "completed"
                 and calls[0].get("model_completion") is True and receipt.get("schema_valid") is True
                 and receipt.get("host_client") == account["host_client"]
                 and receipt.get("source_job_id") == state["binding"]["source_job_id"]
                 and all(calls[0]["usage"][name] == receipt.get(name) for name in ("input_tokens", "output_tokens"))
                 and abs(calls[0]["usage"]["duration_seconds"] - receipt.get("duration_seconds", -100)) < .01
                 and attempts[0].get("status") == attempts[0].get("terminal") == "completed"
                 and attempts[0].get("model_dispatched") is True
                 and attempts[0].get("unknown_response_usage_count") == 0, "budget_native_receipt_changed")
        hashes = [receipt.get("input_sha256"), receipt.get("response_sha256"),
                  attempts[0].get("input_sha256"), attempts[0].get("response_text_sha256")]
        _require(all(isinstance(value, str) and len(value) == 64
                     and all(char in "0123456789abcdef" for char in value) for value in hashes)
                 and (phase == "assimilate" or hashes[:2] == hashes[2:]), "budget_native_hash_changed")
    return {"contract": "source-coverage-budget-interruption-v1", "run_id": origin.id, "reason": reason,
        "task_scope": account["task_scope"], "host_client": account["host_client"],
        "snapshot_sha256": _digest(snapshot), "account_prefix_count": count,
        "account_prefix_sha256": _digest(prefix), "native_receipts_sha256": _digest(receipts)}


async def _commit_ancestor(backend: Any, *, origin: Any, frozen: dict, key: str,
                           project_name: str, project_root: str | Path,
                           seen: frozenset[str] = frozenset()) -> tuple[dict, list[dict]]:
    """A zero-write audit child inherits its source anchor, never a commit."""
    _require(origin.id not in seen, "ancestor_cycle")
    state = _source_ledger(origin)["source_coverage"][key]
    if state.get("commit_bindings"):
        return state, []
    _require(frozen.get("contract") == CONTRACT, "committed_anchor_missing")
    parent, parent_frozen, parent_account = await _origin(backend,
        project_name=project_name, project_root=project_root,
        origin_run_id=frozen.get("origin_run_id", ""), run_id=origin.id, predecessor_ids=[key])
    raw = backend.structured_store._canonical.get_payload_json("dream_runs", parent.id)
    _require(raw is not None and _raw_digest(raw) == frozen.get("origin_payload_sha256")
             and frozen.get("task_scope") == parent_account.get("task_scope")
             and frozen.get("host_client") == parent_account.get("host_client"), "ancestor_changed")
    parent_state = _source_ledger(parent)["source_coverage"][key]
    fields = ("predecessor_id", "predecessor_sha256", "source_id", "source_revision",
              "source_job_id", "source_job_sha256", "context_sha256")
    _require(all(state["binding"].get(name) == parent_state["binding"].get(name)
                 for name in fields), "ancestor_source_changed")
    anchor, chain = await _commit_ancestor(backend, origin=parent, frozen=parent_frozen, key=key,
        project_name=project_name, project_root=project_root, seen=seen | {origin.id})
    return anchor, [{"run_id": parent.id, "payload_sha256": _raw_digest(raw),
                     "source_state_sha256": _digest(parent_state)}, *chain]


async def _project_comparisons(backend: Any, *, project_name: str,
                                project_root: str | Path, successor_ids: Sequence[str]) -> list[dict]:
    """Project comparisons carry no source approval or write-target authority."""
    store = backend.structured_store.knowledge_store
    result = []
    for entry in await store.list_entries(project_name, project_root=project_root):
        if entry.project_name != project_name or entry.source_report is not None or entry.id in successor_ids:
            continue
        try:
            refs = await store.list_sources(entry.id)
            source_versions = deepcopy(refs)
            valid = bool(refs)
            for ref in refs:
                query = parse_qs(urlparse(ref.locator).fragment)
                if (ref.source_kind != "user_statement" or ref.project_name != project_name
                        or ref.knowledge_id != entry.id
                        or any(len(query.get(name, [])) != 1 for name in ("source_id", "source_revision", "exchange"))):
                    valid = False
                    break
                outcome, _reason, content, truncated, _effective = coverage._reopen_complete_user_context(backend, ref)
                revision = backend.transcript_store.get_revision(query["source_id"][0], query["source_revision"][0])
                body = json.loads(content) if outcome == "verified" and content and not truncated else None
                if (not isinstance(body, dict) or revision is None
                        or body.get("context_scope") != "complete-authored-user-v1"
                        or body.get("role") != "user" or body.get("project_name") != project_name
                        or body.get("source_id") != revision.source_id
                        or body.get("source_revision") != revision.source_revision
                        or body.get("session_id") != revision.session_id
                        or revision.project_name != project_name
                        or Path(revision.project_root).resolve() != Path(project_root).resolve()):
                    valid = False
                    break
            snapshot = coverage._entry_version_snapshot(entry)
            current = await store.get_entry(entry.id, project_name=project_name, project_root=project_root)
            if (valid and current is not None and coverage._entry_version_snapshot(current) == snapshot
                    and await store.list_sources(entry.id) == source_versions):
                result.append({**snapshot, "comparison_only": True,
                               "kind": "current_knowledge_comparison_not_source_evidence"})
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return sorted(result, key=lambda row: row["id"])


async def _later_user_contexts(backend: Any, prepared: Mapping[str, Any], *,
                                project_name: str, project_root: str | Path,
                                original_binding: Mapping[str, Any],
                                required_context_hashes: Sequence[str] = ()) -> tuple[list[dict], dict]:
    """Reopen same-session extensions separately from the frozen old windows."""
    from harness_mem.autonomous.provider import _later_coverage_windows

    old = prepared["binding"]
    store = backend.structured_store.knowledge_store
    packets = {}
    opened = set()
    for entry in await store.list_entries(project_name, project_root=project_root):
        if entry.project_name != project_name or entry.source_report is not None:
            continue
        for ref in await store.list_sources(entry.id):
            if (ref.source_kind != "user_statement" or ref.project_name != project_name
                    or ref.knowledge_id != entry.id):
                continue
            try:
                query = parse_qs(urlparse(ref.locator).fragment)
                if (query.get("source_id") != [old["source_id"]]
                        or len(query.get("source_revision", [])) != 1):
                    continue
                revision_id = query["source_revision"][0]
                if revision_id == old["source_revision"]:
                    continue
                revision = backend.transcript_store.get_revision(old["source_id"], revision_id)
                if (revision is None or revision.project_name != project_name
                        or revision.source_id != old["source_id"] or revision.source_revision != revision_id
                        or revision.session_id != original_binding["session_id"]
                        or revision.client != original_binding["client"]
                        or Path(revision.project_root).resolve() != Path(project_root).resolve()):
                    continue
                identity = (ref.locator, getattr(ref, "content_sha256", None))
                if identity in opened:
                    continue
                opened.add(identity)
                outcome, _reason, content, truncated, _effective = coverage._reopen_complete_user_context(backend, ref)
                if outcome != "verified" or not content or truncated:
                    continue
                packet = {"contract": "source-coverage-later-users-v1",
                    "original_context_sha256": old["context_sha256"], "context_sha256": _raw_digest(content),
                    "content": content, "source_id": old["source_id"], "source_revision": revision_id,
                    "session_id": revision.session_id, "client": revision.client, "project_name": project_name,
                    "project_root_sha256": _digest(str(Path(project_root).resolve()))}
                source = {**old, "windows": prepared["authored_user_exchanges"], "later_user_contexts": [packet]}
                _later_coverage_windows(source, original_binding=dict(original_binding))
                packets[packet["context_sha256"]] = packet
            except (ValueError, KeyError, TypeError, OSError):
                continue
    selected = _maximal_later_contexts([packets[key] for key in sorted(packets)], required_context_hashes)
    source = {**old, "windows": prepared["authored_user_exchanges"], "later_user_contexts": selected}
    return selected, _later_coverage_windows(source, original_binding=dict(original_binding))


def _maximal_later_contexts(packets: Sequence[dict], required_context_hashes: Sequence[str]) -> list[dict]:
    """Drop only exact authored-user prefixes; preserve referenced revisions."""
    histories = [[(row["exchange_index"], tuple(row["messages"]))
                  for row in json.loads(packet["content"])["authored_exchanges"]] for packet in packets]
    return [packet for index, packet in enumerate(packets)
            if packet["context_sha256"] in required_context_hashes or not any(
                len(other) > len(histories[index]) and other[:len(histories[index])] == histories[index]
                for other in histories)]


def _audit_windows(state: Mapping[str, Any], authored: Sequence[Mapping[str, Any]], old_count: int,
                   later_windows: Mapping[str, Any] | None = None) -> tuple[list, dict]:
    audit = state.get("inventory_verification") or {}
    hashes = {"input_sha256", "inventory_sha256", "candidate_output_sha256", "verification_rows_sha256",
              "candidate_verification_sha256", "audit_binding_sha256", "summary_sha256"}
    fields = hashes | {"windows", "audit", "extracted_point_sha256"}
    _require(set(audit) in (fields, fields | {"admission_mode"})
             and audit.get("admission_mode", "full_inventory") in {"selected_points", "full_inventory", "observation"}
             and all(isinstance(audit.get(key), str) and len(audit[key]) == 64
                     and all(char in "0123456789abcdef" for char in audit[key]) for key in hashes), "summary_invalid")
    _require(audit.get("summary_sha256") == _digest({k: v for k, v in audit.items() if k != "summary_sha256"}),
             "summary_changed")
    _require(audit.get("inventory_sha256") == _digest({k: audit.get(k) for k in (
        "input_sha256", "candidate_output_sha256", "windows")}), "inventory_changed")
    audit_body = {k: audit.get(k) for k in ("input_sha256", "inventory_sha256", "candidate_output_sha256",
        "verification_rows_sha256", "candidate_verification_sha256", "audit")}
    _require(audit.get("audit_binding_sha256") == _digest(audit_body), "votes_changed")
    workspace = state.get("inventory_workspace") or {}
    _require(workspace.get("input_sha256") == audit.get("input_sha256"), "workspace_input_changed")
    windows = [SourceCoverageWindow.model_validate(row).model_dump(mode="json") for row in audit.get("windows") or []]
    _require([row["w"] for row in windows] == list(range(len(authored))), "windows_incomplete")
    point_count = len(audit.get("extracted_point_sha256") or [])
    _require(point_count == len(state.get("candidate_ids") or [])
             and [row.get("id") for row in workspace.get("workspace") or []] == state.get("candidate_ids"),
             "workspace_points_changed")
    expected = set()
    for window in windows:
        w, cursor = window["w"], 0
        for index, span in enumerate(window["spans"]):
            expected.add((w, index))
            _require(span["s"] == cursor and cursor < span["e"] <= len(authored[w]["text"]), "range_changed")
            cursor = span["e"]
            if span["d"] == "covered":
                _require(span["c"] and not span["p"] and not span["r"]
                         and all(value < old_count for value in span["c"]), "current_link_invalid")
            elif span["d"] == "extract":
                _require(span["p"] and not span["c"] and not span["r"]
                         and all(value < point_count for value in span["p"]), "point_link_invalid")
            elif span["d"] == "superseded":
                _require(span["r"] and not span["p"] and not span["c"], "later_link_invalid")
                for ref in span["r"]:
                    if "w" in ref:
                        _require(ref["w"] < len(authored) and ref["s"] < ref["e"] <= len(authored[ref["w"]]["text"])
                                 and authored[ref["w"]]["exchange_index"] > authored[w]["exchange_index"], "later_link_invalid")
                    else:
                        correction = (later_windows or {}).get(ref["context_sha256"], {}).get(
                            (ref["exchange_index"], ref["message_index"]))
                        _require(correction is not None and ref["exchange_index"] > max(
                            row["exchange_index"] for row in authored)
                            and correction["sha256"] == ref["content_sha256"]
                            and ref["s"] < ref["e"] <= len(correction["text"]), "later_link_invalid")
            else:
                _require(not span["p"] and not span["c"] and not span["r"], "hidden_link")
        _require(cursor == len(authored[w]["text"]), "range_incomplete")
    votes = [SourceCoverageAuditPoint.model_validate(row).model_dump(mode="json") for row in audit.get("audit") or []]
    identities = [(row.get("w"), row.get("span_index")) for row in votes]
    _require(len(identities) == len(set(identities)) and set(identities) == expected
             and all(row.get("verdict") in {"supported", "unclear", "contradicted"} for row in votes),
             "votes_incomplete")
    return windows, {identity: row for identity, row in zip(identities, votes)}


async def _applied_anchors(backend: Any, state: Mapping[str, Any], project_name: str,
                           project_root: str | Path) -> list[str]:
    store = backend.structured_store.knowledge_store
    anchors = []
    for proof in state.get("commit_bindings") or []:
        _require(proof.get("status") == "applied" and proof.get("candidate_id") in state.get("committed_candidate_ids", [])
                 and await store.current_change_committed(proof.get("decision_id", "")), "commit_unproved")
        ids, hashes = proof.get("truth_ids") or [], proof.get("truth_sha256") or []
        _require(ids and len(ids) == len(hashes), "commit_unproved")
        for identity, expected in zip(ids, hashes):
            entry = await store.get_entry(identity, project_name=project_name, project_root=project_root)
            _require(entry is not None and entry.source_report is None
                     and _digest({"title": entry.title, "statement": entry.statement,
                                  "topic_path": entry.module_path}) == expected, "committed_truth_changed")
            anchors.append(identity)
        for identity in proof.get("predecessor_ids") or []:
            _require(await store.get_entry(identity, project_name=project_name, project_root=project_root) is None,
                     "committed_predecessor_current")
    _require(anchors and len(anchors) == len(set(anchors)), "committed_anchor_missing")
    return anchors


async def _deferred_workspace(backend: Any, state: Mapping[str, Any],
                               resolved_candidate_ids: Sequence[str] = ()) -> list[dict]:
    """Bind unresolved work through its actual workspace, never canonical tables."""
    store = backend.structured_store.knowledge_store
    original = {row["id"]: row for row in (state.get("inventory_workspace") or {}).get("workspace") or []}
    result = []
    committed = set(state.get("committed_candidate_ids") or [])
    for outcome in state.get("candidate_outcomes") or []:
        identity = outcome.get("candidate_id")
        if identity in committed or identity in resolved_candidate_ids:
            continue
        _require(outcome.get("disposition") == "handoff" and outcome.get("status") == "deferred"
                 and not outcome.get("truth_ids") and identity in original, "unresolved_candidate_invalid")
        candidate, evidence = await store.get_candidate(identity), await store.list_evidence(identity)
        _require(candidate is not None and candidate.status == "deferred" and len(evidence) == 1,
                 "deferred_workspace_missing")
        prior = {**candidate.to_dict(), "status": "pending"}
        _require(_digest(prior) == original[identity]["candidate_sha256"]
                 and _digest(evidence[0].to_dict()) == original[identity]["evidence_sha256"]
                 and evidence[0].verification_outcome == "verified"
                 and evidence[0].distill_job_id == state["binding"]["source_job_id"], "deferred_workspace_changed")
        handoff_id = outcome.get("handoff_id")
        _require(isinstance(handoff_id, str) and bool(handoff_id), "handoff_unproved")
        raw = backend.structured_store._canonical.get_payload_json("task_handoffs", handoff_id)
        handoff = json.loads(raw) if raw else None
        _require(isinstance(handoff, dict) and handoff.get("project_name") == candidate.project_name
                 and (handoff.get("context") or {}).get("candidate_id") == identity
                 and (handoff.get("context") or {}).get("distill_job_id") == evidence[0].distill_job_id,
                 "handoff_unproved")
        result.append({"candidate_id": identity, "candidate_sha256": _digest(candidate.to_dict()),
                       "evidence_sha256": _digest(evidence[0].to_dict()), "handoff_id": handoff_id,
                       "handoff_sha256": _raw_digest(raw), "original_workspace": original[identity]})
    return result


async def _observed_workspace(backend: Any, state: Mapping[str, Any], prepared: Mapping[str, Any]) -> list[dict]:
    """Reopen unadmitted proposals as pending source work, never handoffs."""
    from harness_mem.autonomous.provider import source_coverage_audit_has_unresolved

    summary = state.get("inventory_verification") or {}
    _require(summary.get("admission_mode") == "observation" and source_coverage_audit_has_unresolved(summary)
             and not state.get("commit_bindings") and not state.get("committed_candidate_ids")
             and not state.get("candidate_outcomes"), "observed_workspace_authority_invalid")
    store = backend.structured_store.knowledge_store
    workspace = state["inventory_workspace"]["workspace"]
    identities = state["candidate_ids"]
    points = summary["extracted_point_sha256"]
    anchors = {row["exchange_index"]: row["content_sha256"]
               for row in prepared["packet"]["semantic_decision_exchanges"]}
    _require(len(identities) == len(set(identities)) == len(points) == len(workspace),
             "observed_workspace_incomplete")
    result = []
    for index, (identity, expected) in enumerate(zip(identities, workspace)):
        candidate = await store.get_candidate(identity)
        evidence = await store.list_evidence(identity)
        _require(candidate is not None and candidate.status == "pending"
                 and candidate.project_name == prepared["job"].project_name
                 and candidate.source_report is None and expected.get("id") == identity
                 and _digest(candidate.to_dict()) == expected.get("candidate_sha256") and len(evidence) == 1,
                 "observed_candidate_changed")
        proof = evidence[0]
        _require(_digest(proof.to_dict()) == expected.get("evidence_sha256")
                 and proof.candidate_id == identity and proof.project_name == candidate.project_name
                 and proof.distill_job_id == prepared["job"].id
                 and proof.verification_outcome == "unverified" and proof.evidence_basis == "user_statement"
                 and "source_coverage_inventory_observation_unresolved" in proof.verification_reason_codes
                 and bool(proof.verification_refs)
                 and all(ref.kind == "user_statement" and ref.role == "user"
                         and anchors.get(ref.exchange_index) == ref.content_sha256 for ref in proof.verification_refs),
                 "observed_evidence_changed")
        _require(not candidate.assimilation_disposition and not candidate.assimilation_target_ids
                 and not candidate.assimilation_targets, "observed_candidate_admission_claimed")
        result.append({"point_index": index, "point_sha256": points[index], "candidate_id": identity,
            "candidate_sha256": expected["candidate_sha256"], "evidence_sha256": expected["evidence_sha256"],
            "source_id": prepared["binding"]["source_id"],
            "source_revision": prepared["binding"]["source_revision"],
            "source_job_id": prepared["job"].id, "source_job_sha256": prepared["binding"]["source_job_sha256"],
            "status": "pending", "admission": "blocked_inventory_observation"})
    return result


async def _budget_workspace(backend: Any, origin: Any, state: Mapping[str, Any], prepared: Mapping[str, Any],
                            source: dict, original_context: dict) -> list[dict]:
    """Bind verified but uncommitted extracts as pending, never as writes or handoffs."""
    from harness_mem.autonomous.provider import source_coverage_audit_binding_block
    from harness_mem.commands.evidence_admission import _frozen_user_exchange_indexes
    from harness_mem.commands.separated_assimilation import _statement
    from harness_mem.autonomous.worker import _candidate_statement_from_arguments

    scope = {"kind": "runtime_maintenance_scope_not_source_evidence", "contract": coverage.CONTRACT,
        "retain_still_applicable_scoped_conditions": True, "run_id": origin.id,
        "predecessor_id": state["binding"]["predecessor_id"], "current_successors": prepared["successors"],
        "inventory_input": source, "inventory_audit_repair": {"original_context_binding": original_context,
            "later_user_contexts": source.get("later_user_contexts", [])}}
    summary = state["inventory_verification"]
    _require(summary.get("admission_mode") == "selected_points"
             and source_coverage_audit_binding_block(summary, {"source_coverage": scope},
                 admission_mode="selected_points") is None, "budget_inventory_binding_changed")
    proofs = next(row for row in _observation_receipts(origin.to_dict(), state)
                  if row["phase"] == "candidate_verify").get("verification_points") or []
    ids, workspace = state["candidate_ids"], state["inventory_workspace"]["workspace"]
    _require(ids and len(ids) == len(set(ids)) == len(workspace) == len(proofs)
             and state.get("candidate_status_counts") == {"pending": len(ids)}, "budget_workspace_incomplete")
    _revision, rendering, _raw = coverage._source_report_context(backend, project_name=prepared["job"].project_name,
        source_id=source["source_id"], source_revision=source["source_revision"])
    authors = _frozen_user_exchange_indexes(backend, source_id=source["source_id"],
        source_revision=source["source_revision"], rendering=rendering, allow_legacy_explicit=False)
    anchors = {row["exchange_index"]: row["content_sha256"]
               for row in prepared["packet"]["semantic_decision_exchanges"]}
    result, outcomes = [], []
    store = backend.structured_store.knowledge_store
    for index, (identity, expected, proof) in enumerate(zip(ids, workspace, proofs)):
        candidate, evidence = await store.get_candidate(identity), await store.list_evidence(identity)
        _require(candidate is not None and candidate.status == "pending" and candidate.source_report is None
                 and candidate.project_name == prepared["job"].project_name and expected["id"] == identity
                 and _digest(candidate.to_dict()) == expected["candidate_sha256"] and len(evidence) == 1
                 and candidate.assimilation_disposition is None and not candidate.assimilation_target_ids
                 and not candidate.assimilation_targets, "budget_candidate_changed")
        evidence = evidence[0]
        _require(_digest(evidence.to_dict()) == expected["evidence_sha256"]
                 and evidence.candidate_id == identity and evidence.project_name == candidate.project_name
                 and evidence.distill_job_id == prepared["job"].id and evidence.evidence_basis == "user_statement"
                 and evidence.verification_outcome == "verified" and evidence.verification_refs and authors
                 and all(ref.kind == "user_statement" and ref.role == "user" and ref.locator is None
                     and ref.exchange_index in authors and anchors.get(ref.exchange_index) == ref.content_sha256
                     for ref in evidence.verification_refs), "budget_evidence_or_source_changed")
        native_hashes = {_raw_digest(candidate.statement)}
        if candidate.candidate_type == "rule":
            for separator in ("：", ": "):
                for offset in range(len(candidate.statement)):
                    if candidate.statement.startswith(separator, offset):
                        arguments = {"kind": "rule", "trigger": candidate.statement[:offset],
                                     "pattern": candidate.statement[offset + len(separator):]}
                        if " ".join(_statement(arguments, kind="rule").split()) == candidate.statement:
                            native_hashes.add(_raw_digest(_candidate_statement_from_arguments(arguments)))
        _require(proof.get("candidate_index") == index and proof.get("semantic_support") == "supported"
                 and proof.get("future_scope") == "durable" and proof.get("scope_text_sha256") in native_hashes,
                 "budget_candidate_native_proof_changed")
        outcomes.append({"candidate_id": identity, "candidate_sha256": expected["candidate_sha256"], "status": "pending"})
        result.append({"point_index": index, "point_sha256": summary["extracted_point_sha256"][index],
            "candidate_id": identity, "candidate_sha256": expected["candidate_sha256"],
            "evidence_sha256": expected["evidence_sha256"], "status": "pending", "admission": "blocked_budget_interruption"})
    _require(state.get("candidate_outcomes") == outcomes, "budget_outcomes_or_handoff_changed")
    return result


async def _resolved_no_write_binding(backend: Any, proof: Mapping[str, Any],
                                      resolved: Mapping[str, Any]) -> dict:
    """Prove a completed common-owner no-write without claiming coverage."""
    identity, writer = resolved["original_candidate_id"], resolved["writing_candidate_id"]
    canonical = backend.structured_store._canonical
    raw = canonical.get_payload_json("dream_runs", proof["recovery_run_id"])
    carrier = await backend.structured_store.get_dream_run(proof["recovery_run_id"])
    _require(raw is not None and _raw_digest(raw) == proof["payload_sha256"]
             and carrier is not None and _digest(json.loads(raw)) == _digest(carrier.to_dict()),
             "recovery_no_write_carrier_changed")
    state = carrier.continuation.get("source_handoff_recovery") or {}
    binding = state.get("binding") or {}
    _require(state.get("binding_sha256") == _digest(binding) == proof["binding_sha256"]
             and binding.get("run_id") == proof["recovery_run_id"]
             and binding.get("origin_run_id") == proof["origin_run_id"]
             and binding.get("source_job_id") == proof["source_job_id"], "recovery_no_write_binding_changed")
    points = resolved.get("point_proofs") or []
    _require(points and not resolved.get("commit_bindings")
             and all(row.get("disposition") == "no_write" and row.get("truth_ids") == []
                     and row.get("truth_bindings") == [] for row in points), "recovery_no_write_truth_claimed")
    outcomes = [row for row in state.get("canonical_outcomes") or []
                if row.get("original_candidate_id") == identity and row.get("candidate_id") == writer]
    _require(len(outcomes) == 1 and outcomes[0].get("status") == "resolved"
             and outcomes[0].get("point_proofs") == points
             and outcomes[0].get("candidate_sha256") == resolved["writing_candidate_sha256"]
             and outcomes[0].get("terminal_evidence_sha256") == resolved["writing_evidence_sha256"]
             and outcomes[0].get("handoff_id") == resolved["handoff_id"]
             and not any(row.get("candidate_id") == writer for row in state.get("commit_bindings") or []),
             "recovery_no_write_outcome_changed")
    receipts = [row for row in state.get("apply_outcomes") or [] if row.get("candidate_id") == writer]
    _require(len(receipts) == 1 and receipts[0].get("disposition") == "no_write"
             and receipts[0].get("canonical_truth_ids") == [] and receipts[0].get("handoff_id") is None,
             "recovery_no_write_receipt_missing")
    expected_path = (Path(backend.data_dir) / "autonomous" / "provider-runtime"
                     / ("source-handoff-plan-" + _digest(binding) + ".json")).resolve()
    _require(isinstance(state.get("plan_path"), str)
             and Path(state["plan_path"]).resolve() == expected_path, "recovery_no_write_plan_changed")
    plan_bytes = expected_path.read_bytes()
    _require(hashlib.sha256(plan_bytes).hexdigest() == state.get("plan_sha256"), "recovery_no_write_plan_changed")
    plan = json.loads(plan_bytes)
    selected = [row for row in plan.get("points") or [] if row.get("candidate_id") == writer]
    _require(plan.get("version") == "separated-v1" and writer in (plan.get("candidate_ids") or [])
             and plan.get("point_count") == len(plan.get("points") or [])
             and len(selected) == len(points) == len(receipts) == 1
             and selected[0].get("disposition") == "no_write"
             and not selected[0].get("matched_truth_ids") and not selected[0].get("knowledge_items")
             and _digest(selected[0]) == points[0].get("point_sha256"), "recovery_no_write_plan_changed")
    handoff = await backend.structured_store.get_task_handoff(resolved["handoff_id"])
    witness = {"contract": proof["contract"], "binding_sha256": proof["binding_sha256"],
        "run_id": proof["recovery_run_id"], "source_job_id": proof["source_job_id"],
        "original_candidate_id": identity, "points_sha256": _digest(points)}
    _require(handoff is not None and handoff.status == "done"
             and handoff.context.get("source_handoff_resolution") == witness, "recovery_no_write_handoff_changed")
    result_hash = state.get("result_sha256")
    _require(isinstance(result_hash, str) and len(result_hash) == 64
             and all(char in "0123456789abcdef" for char in result_hash), "recovery_no_write_receipt_missing")
    return {"recovery_payload_sha256": proof["payload_sha256"], "binding_sha256": proof["binding_sha256"],
        "plan_sha256": state["plan_sha256"], "point_sha256": points[0]["point_sha256"],
        "common_result_sha256": result_hash, "common_no_write_receipt": deepcopy(receipts[0]),
        "common_no_write_receipt_sha256": _digest(receipts[0]), "handoff_witness_sha256": _digest(witness)}


async def _deferred_source_evidence(backend: Any, *, origin: Any, state: Mapping[str, Any],
                                    outcome: Mapping[str, Any], evidence: dict,
                                    expected_sha256: str) -> tuple[dict, dict]:
    """Reopen only the common owner's proven partition-rejection annotation."""
    from harness_mem.core.schemas.knowledge import AssimilationDecision
    from harness_mem.storage.knowledge_job_workspace import KnowledgeJobWorkspace

    code = "final_source_scope_partition_missing"
    reason = "Final knowledge scope verification deferred this complete point: " + code + "."
    codes = evidence["verification_reason_codes"]
    _require(outcome.get("disposition") == "defer" and outcome.get("status") == "deferred"
             and outcome.get("truth_ids") == [] and codes.count(code) == 1 and codes[-1] == code,
             "recovery_defer_annotation_unproved")
    finals = [row for row in _observation_receipts(origin.to_dict(), state) if row.get("phase") == "final_scope"]
    _require(len(finals) == 1, "recovery_defer_final_receipt_changed")
    final = finals[0]
    votes = final.get("verification_points") or []
    # This narrow projection recognizes only the single-output partition
    # rejection produced by the common final owner, never a positive proof.
    _require(state.get("candidate_ids") == [outcome["candidate_id"]]
             and final.get("source_job_id") == state["binding"]["source_job_id"]
             and final.get("schema_valid") is True and len(votes) == 1
             and votes[0].get("candidate_index") == 0 and votes[0].get("semantic_support") == "partial"
             and votes[0].get("future_scope") == votes[0].get("source_use") == "unclear"
             and votes[0].get("scope_text_sha256") == _raw_digest("")
             and votes[0].get("scope_segments") == [] and votes[0].get("update_meaning") is None
             and all(isinstance(value, str) and len(value) == 64
                     and all(char in "0123456789abcdef" for char in value)
                     for value in (state.get("plan_sha256"), state.get("result_sha256"), outcome.get("result_sha256"))),
             "recovery_defer_final_receipt_changed")
    workspace = KnowledgeJobWorkspace(Path(backend.data_dir))
    wrappers = [json.loads(path.read_text(encoding="utf-8"))
        for path in (Path(backend.data_dir) / "job_workspaces" / "knowledge" / "decisions").glob("*.json")]
    selected = [row for row in wrappers if (row.get("data") or {}).get("candidate_id") == outcome["candidate_id"]]
    _require(len(selected) == 1, "recovery_defer_decision_changed")
    wrapper = selected[0]
    decision = AssimilationDecision.from_dict(wrapper["data"])
    _require(decision.candidate_id == outcome["candidate_id"]
             and decision.project_name == evidence["project_name"] and decision.disposition == "defer"
             and decision.reason == reason and not decision.canonical_truth_ids
             and not decision.predecessor_truth_ids and not decision.predecessor_entries
             and wrapper.get("workspace_id") == state["binding"]["source_job_id"]
             and json.loads(workspace._decision_path(decision.id).read_text(encoding="utf-8")) == wrapper
             and _digest(wrapper.get("data")) == _digest(decision.to_dict()), "recovery_defer_decision_changed")
    handoff = await backend.structured_store.get_task_handoff(outcome["handoff_id"])
    _require(handoff is not None and handoff.status == "done"
             and handoff.project_name == evidence["project_name"]
             and handoff.context.get("candidate_id") == outcome["candidate_id"]
             and handoff.context.get("distill_job_id") == state["binding"]["source_job_id"]
             and any(reason in step for step in handoff.next_steps), "recovery_defer_handoff_changed")
    projected = {**evidence, "verification_reason_codes": codes[:-1]}
    _require(_digest(projected) == expected_sha256, "recovery_evidence_changed")
    return projected, {"reason_code": code, "decision_sha256": _digest(decision.to_dict()),
        "decision_wrapper_sha256": _digest(wrapper), "handoff_sha256": _digest(handoff.to_dict()),
        "origin_state_sha256": _digest(state), "final_receipt_sha256": _digest(final),
        "plan_sha256": state["plan_sha256"], "result_sha256": state["result_sha256"],
        "point_result_sha256": outcome["result_sha256"],
        "current_source_evidence_sha256": _digest(evidence), "workspace_evidence_sha256": expected_sha256}


async def _recovered_points(backend: Any, *, origin: Any, state: Mapping[str, Any],
                             prepared: Mapping[str, Any], new_ids: Sequence[str],
                             recovery_run_id: str) -> tuple[dict[int, dict], dict, dict[int, dict]]:
    """Bind old extraction indexes to the recovery owner's actual new writes."""
    from harness_mem.commands.source_handoff_recovery import read_source_handoff_recovery_proof

    proof = await read_source_handoff_recovery_proof(backend, run_id=recovery_run_id,
        origin_run_id=origin.id, source_job_id=state["binding"]["source_job_id"])
    _require(proof.get("task_scope") == _source_ledger(origin).get("task_scope")
             and all(proof.get(name) == state["binding"].get(name)
                     for name in ("source_id", "source_revision", "source_job_id")), "recovery_scope_changed")
    identities = state.get("candidate_ids") or []
    workspace = {row["id"]: row for row in state["inventory_workspace"]["workspace"]}
    outcomes = {row["candidate_id"]: row for row in state.get("candidate_outcomes") or []}
    anchors = {row["exchange_index"]: row["content_sha256"]
               for row in prepared["packet"]["semantic_decision_exchanges"]}
    store = backend.structured_store.knowledge_store
    result = {}
    resolved_no_write = {}
    for resolved in proof.get("resolved") or []:
        identity = resolved.get("original_candidate_id")
        if identity not in identities:
            continue
        index = identities.index(identity)
        _require(index not in result and identity in workspace, "recovery_point_duplicate")
        original = resolved.get("original_binding") or {}
        outcome = outcomes.get(identity) or {}
        candidate, evidence = await store.get_candidate(identity), await store.list_evidence(identity)
        _require(candidate is not None and len(evidence) == 1
                 and original.get("original_candidate_id") == identity
                 and original.get("mode") == "retained_workspace"
                 and outcome.get("disposition") in {"handoff", "defer"}
                 and original.get("handoff_id") == outcome.get("handoff_id") == resolved.get("handoff_id")
                 and original.get("original_point_sha256") == _digest({"point": outcome,
                     "mode": "inventory_workspace", "state_sha256": _digest(state)})
                 and _digest({**candidate.to_dict(), "status": "pending"}) == workspace[identity]["candidate_sha256"]
                 and original.get("candidate_sha256") == _digest(candidate.to_dict())
                 and original.get("evidence_sha256") == _digest([row.to_dict() for row in evidence]),
                 "recovery_original_changed")
        original_evidence = deepcopy(evidence[0].to_dict())
        original_evidence["verification_reason_codes"] = [code for code in
            original_evidence["verification_reason_codes"] if not (
                isinstance(code, str) and code.startswith("fsv_") and len(code) == 64
                and all(char in "0123456789abcdef" for char in code[4:]))]
        evidence_reopen = None
        if _digest(original_evidence) != workspace[identity]["evidence_sha256"]:
            original_evidence, evidence_reopen = await _deferred_source_evidence(backend, origin=origin, state=state,
                outcome=outcome, evidence=original_evidence, expected_sha256=workspace[identity]["evidence_sha256"])
        _require(_digest(original_evidence) == workspace[identity]["evidence_sha256"]
                 and evidence[0].evidence_basis == "user_statement"
                 and evidence[0].verification_outcome == "verified"
                 and evidence[0].distill_job_id == state["binding"]["source_job_id"]
                 and bool(evidence[0].verification_refs), "recovery_evidence_changed")
        exchanges = set()
        for ref in evidence[0].verification_refs:
            _require(ref.kind == "user_statement" and ref.role == "user"
                     and anchors.get(ref.exchange_index) == ref.content_sha256, "recovery_source_changed")
            exchanges.add(ref.exchange_index)
        writing_id = resolved.get("writing_candidate_id")
        writing = await store.get_candidate(writing_id)
        writing_evidence = await store.list_evidence(writing_id)
        _require(writing is not None and writing_id != identity and writing.status == "assimilated"
                 and writing.project_name == candidate.project_name
                 and writing.candidate_type == candidate.candidate_type
                 and writing.statement == candidate.statement and writing.source_report == candidate.source_report
                 and _digest(writing.to_dict()) == resolved.get("writing_candidate_sha256")
                 and len(writing_evidence) == 1
                 and writing_evidence[0].candidate_id == writing_id
                 and writing_evidence[0].distill_job_id == state["binding"]["source_job_id"]
                 and writing_evidence[0].evidence_basis == evidence[0].evidence_basis
                 and writing_evidence[0].verification_refs == evidence[0].verification_refs
                 and _digest([row.to_dict() for row in writing_evidence]) == resolved.get("writing_evidence_sha256"),
                 "recovery_writing_changed")
        point_proofs = resolved.get("point_proofs") or []
        if point_proofs and all(row.get("disposition") == "no_write" for row in point_proofs):
            no_write = await _resolved_no_write_binding(backend, proof, resolved)
            resolved_no_write[index] = {"original_point_index": index, "candidate_id": identity,
                "writing_candidate_id": writing_id, "recovery_run_id": recovery_run_id,
                "recovery_proof_sha256": _digest(proof), "source_exchange_indexes": sorted(exchanges),
                "original_workspace": workspace[identity], "canonical_no_write_binding": no_write,
                "coverage_authority": False}
            if evidence_reopen is not None:
                resolved_no_write[index]["source_evidence_reopen"] = evidence_reopen
            continue
        if not point_proofs or any(row.get("disposition") not in {"add", "replace", "refine", "confirm"}
                or not row.get("truth_ids") or not row.get("truth_bindings") for row in point_proofs):
            continue  # A generic no-write or unbound confirmation is not coverage.
        commits = resolved.get("commit_bindings") or []
        if any(row.get("disposition") != "confirm" for row in point_proofs):
            _require(commits and all(row.get("candidate_id") == writing_id
                     and row.get("original_candidate_id") == identity
                     and row.get("status") == "applied" for row in commits), "recovery_commit_missing")
        truth = {}
        for point_proof in point_proofs:
            _require(set(point_proof["truth_ids"]) == {row.get("id") for row in point_proof["truth_bindings"]},
                     "recovery_truth_incomplete")
            if point_proof["disposition"] != "confirm":
                matching = [row for row in commits if row.get("point_sha256") == point_proof.get("point_sha256")
                            and row.get("truth_ids") == point_proof["truth_ids"]
                            and row.get("truth_bindings") == point_proof["truth_bindings"]]
                _require(len(matching) == 1, "recovery_point_commit_mismatch")
            for bound in point_proof["truth_bindings"]:
                truth_id = bound["id"]
                entry = await store.get_entry(truth_id, project_name=candidate.project_name)
                raw = backend.structured_store._canonical.get_payload_json("knowledge_entries", truth_id)
                refs = await store.list_sources(truth_id)
                _require(truth_id in new_ids and entry is not None and entry.source_report is None
                         and raw is not None and _raw_digest(raw) == bound.get("payload_sha256"),
                         "recovery_truth_changed")
                truth[truth_id] = {"id": truth_id, "current_index": new_ids.index(truth_id),
                    "payload_sha256": _digest(entry.to_dict()),
                    "scope_sha256": _digest(coverage._entry_version_snapshot(entry)),
                    "sources_sha256": _digest([ref.to_dict() for ref in refs])}
        result[index] = {"candidate_id": identity, "writing_candidate_id": writing_id,
            "commit_bindings": deepcopy(commits), "truth_bindings": list(truth.values()),
            "source_exchange_indexes": exchanges, "recovery_run_id": recovery_run_id,
            "recovery_proof_sha256": _digest(proof), "original_workspace": workspace[identity],
            "recovery_point_binding": deepcopy(resolved)}
        if evidence_reopen is not None:
            result[index]["source_evidence_reopen"] = evidence_reopen
    return result, proof, resolved_no_write


async def _committed_points(backend: Any, state: Mapping[str, Any], prepared: Mapping[str, Any],
                            new_ids: Sequence[str]) -> dict[int, dict]:
    """Prove old point indexes from their workspace through the real commit.

    A pending point cannot acquire this exception by naming a committed truth.
    The original candidate and source evidence must still bind; the only
    permitted evidence addition is the final-scope marker from the shared owner.
    """
    store = backend.structured_store.knowledge_store
    identities = state["candidate_ids"]
    workspace = {row["id"]: row for row in state["inventory_workspace"]["workspace"]}
    outcomes = {row["candidate_id"]: row for row in state.get("candidate_outcomes") or []}
    anchors = {row["exchange_index"]: row["content_sha256"]
               for row in prepared["packet"]["semantic_decision_exchanges"]}
    result = {}
    for proof in state.get("commit_bindings") or []:
        identity = proof["candidate_id"]
        _require(identities.count(identity) == 1 and identity in workspace, "committed_point_mismatch")
        outcome = outcomes.get(identity) or {}
        _require(outcome.get("status") == "assimilated"
                 and outcome.get("disposition") in {"add", "refine", "replace"}
                 and outcome.get("truth_ids") == proof["truth_ids"], "committed_outcome_mismatch")
        candidate, evidence = await store.get_candidate(identity), await store.list_evidence(identity)
        _require(candidate is not None and candidate.project_name == prepared["job"].project_name
                 and candidate.status == "assimilated" and len(evidence) == 1,
                 "committed_workspace_missing")
        pending = {**candidate.to_dict(), "status": "pending"}
        _require(_digest(pending) == workspace[identity]["candidate_sha256"], "committed_candidate_changed")
        current_evidence = evidence[0].to_dict()
        original_evidence = deepcopy(current_evidence)
        # final_scope_verification_code is fsv_ plus sixty lowercase hex digits.
        original_evidence["verification_reason_codes"] = [code for code in
            current_evidence["verification_reason_codes"] if not (
                isinstance(code, str) and code.startswith("fsv_") and len(code) == 64
                and all(char in "0123456789abcdef" for char in code[4:]))]
        _require(_digest(original_evidence) == workspace[identity]["evidence_sha256"]
                 and evidence[0].evidence_basis == "user_statement"
                 and evidence[0].project_name == candidate.project_name and evidence[0].candidate_id == identity
                 and evidence[0].verification_outcome == "verified"
                 and evidence[0].distill_job_id == state["binding"]["source_job_id"]
                 and bool(evidence[0].verification_refs), "committed_evidence_changed")
        exchanges = set()
        for ref in evidence[0].verification_refs:
            _require(ref.kind == "user_statement" and ref.role == "user"
                     and anchors.get(ref.exchange_index) == ref.content_sha256, "committed_source_changed")
            exchanges.add(ref.exchange_index)
        truth = []
        for truth_id, expected in zip(proof["truth_ids"], proof["truth_sha256"]):
            _require(truth_id in new_ids, "committed_truth_outside_current")
            entry = await store.get_entry(truth_id, project_name=candidate.project_name)
            _require(entry is not None and entry.source_report is None
                     and _digest({"title": entry.title, "statement": entry.statement,
                                  "topic_path": entry.module_path}) == expected, "committed_truth_changed")
            refs = await store.list_sources(truth_id)
            truth.append({"id": truth_id, "current_index": new_ids.index(truth_id),
                          "payload_sha256": _digest(entry.to_dict()),
                          "scope_sha256": _digest(coverage._entry_version_snapshot(entry)),
                          "sources_sha256": _digest([ref.to_dict() for ref in refs])})
        result[identities.index(identity)] = {"candidate_id": identity, "commit": deepcopy(proof),
            "truth_bindings": truth, "source_exchange_indexes": exchanges,
            "candidate_sha256": _digest(candidate.to_dict()), "evidence_sha256": _digest(current_evidence),
            "original_workspace": workspace[identity]}
    return result


def _clarification_selections(selection: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if selection is None:
        return []
    _require(isinstance(selection, Mapping), "clarification_selection_invalid")
    if "selections" not in selection:
        return [selection]
    values = selection["selections"]
    _require(set(selection) == {"selections"} and isinstance(values, list) and bool(values),
             "clarification_selection_invalid")
    targets = []
    for value in values:
        _require(isinstance(value, Mapping) and set(value) == {"source_ref", "reply", "target"}
                 and isinstance(value["target"], Mapping), "clarification_selection_invalid")
        target = value["target"]
        _require(all(key in target for key in ("source_id", "source_revision", "w", "span_index", "s", "e"))
                 and all(type(target[key]) is int for key in ("w", "span_index", "s", "e")),
                 "clarification_target_invalid")
        _require(not any(all(old[key] == target[key] for key in ("source_id", "source_revision", "w"))
            and (old["span_index"] == target["span_index"] or max(old["s"], target["s"]) < min(old["e"], target["e"]))
            for old in targets), "clarification_target_conflict")
        targets.append(target)
    return values


def _clarification_selection(frozen: Mapping[str, Any], selection: Mapping[str, Any] | None) -> Any:
    """A retained vote keeps its exact parent's source dependency across generations."""
    inherited = frozen.get("clarification_context")
    if selection is None:
        return deepcopy(inherited)
    previous, current = _clarification_selections(inherited), _clarification_selections(selection)
    _require(current[:len(previous)] == previous, "clarification_selection_conflict")
    if inherited is not None and current == previous:
        return deepcopy(inherited)
    if previous:
        return {"selections": deepcopy([*previous, *current[len(previous):]])}
    return deepcopy(selection)


def _clarification_context(backend: Any, prepared: Mapping[str, Any], repair: Mapping[str, Any],
                           selection: Mapping[str, Any], *, inherited: bool = False) -> dict:
    """Reopen one explicit clarification; it cannot supply extract or later-link authority."""
    from urllib.parse import urlencode
    from harness_mem.commands.evidence_admission import _source_report_author_indexes
    from harness_mem.commands.session_inventory import session_reference
    from harness_mem.core.schemas import KnowledgeSource

    _require(isinstance(selection, Mapping) and set(selection) == {"source_ref", "reply", "target"},
             "clarification_selection_invalid")
    ref, reply, target = (selection[name] for name in ("source_ref", "reply", "target"))
    _require(isinstance(ref, dict) and set(ref) == {
        "client", "session_id", "source_id", "source_revision", "reference_id"}
        and all(isinstance(value, str) and value for value in ref.values()), "clarification_source_invalid")
    _require(isinstance(reply, dict) and set(reply) == {"exchange_index", "message_index", "sha256"}
             and type(reply["exchange_index"]) is int and reply["exchange_index"] > 0
             and type(reply["message_index"]) is int and reply["message_index"] >= 0,
             "clarification_reply_invalid")
    _require(isinstance(target, dict) and set(target) == {
        "source_id", "source_revision", "w", "span_index", "s", "e", "sha256"}
        and all(type(target[key]) is int for key in ("w", "span_index", "s", "e"))
        and (inherited or {key: target[key] for key in ("w", "span_index", "s", "e")} in repair["pending_spans"]),
        "clarification_target_invalid")
    old = prepared["binding"]
    _require(all(target[key] == old[key] for key in ("source_id", "source_revision"))
             and 0 <= target["w"] < len(prepared["authored_user_exchanges"])
             and 0 <= target["s"] < target["e"] <= len(prepared["authored_user_exchanges"][target["w"]]["text"])
             and target["sha256"] == prepared["authored_user_exchanges"][target["w"]]["sha256"]
             and ref["source_id"] != old["source_id"], "clarification_original_changed")
    revision, rendering, _raw = coverage._source_report_context(backend,
        project_name=prepared["job"].project_name, source_id=ref["source_id"], source_revision=ref["source_revision"])
    _require(ref == session_reference(revision.client, revision.session_id, revision.source_id, revision.source_revision)
             and revision.session_id == prepared["job"].session_id
             and revision.client == prepared["job"].client
             and Path(revision.project_root).resolve() == Path(prepared["job"].project_root).resolve(),
             "clarification_identity_changed")
    authors = _source_report_author_indexes(revision, rendering, _raw, "user")
    _require(authors and reply["exchange_index"] in authors, "clarification_native_user_unproved")
    windows = coverage.render_distill_exchange_windows(rendering, [reply["exchange_index"]])
    _require(len(windows) == 1, "clarification_reply_missing")
    locator = Path(backend.transcript_store.db_path).resolve().as_uri() + "#" + urlencode({
        "source_id": ref["source_id"], "source_revision": ref["source_revision"],
        "exchange": reply["exchange_index"], "role": "user"})
    descriptor = KnowledgeSource(knowledge_id=old["predecessor_id"], project_name=revision.project_name,
        source_kind="user_statement", locator=locator, content_sha256=windows[0]["content_sha256"],
        verified_at=prepared["job"].created_at)
    status, _reason, content, truncated, _effective = coverage._reopen_complete_user_context(backend, descriptor)
    _require(status == "verified" and content and not truncated, "clarification_user_unproved")
    body = json.loads(content)
    authored = [row for row in body["authored_exchanges"] if row["exchange_index"] == reply["exchange_index"]]
    _require(len(authored) == 1 and reply["message_index"] < len(authored[0]["messages"])
             and _raw_digest(authored[0]["messages"][reply["message_index"]]) == reply["sha256"],
             "clarification_reply_changed")
    return {"contract": "source-coverage-clarification-v1", "selection": deepcopy(dict(selection)),
        "content": content, "context_sha256": _raw_digest(content),
        "raw_sha256": revision.raw_sha256, "rendering_sha256": revision.normalized_sha256,
        "reply_exchange_sha256": windows[0]["content_sha256"]}


async def _prepared(backend: Any, *, origin: Any, frozen: dict, key: str,
                    project_name: str, project_root: str | Path, run_id: str,
                    resolved_handoff_run_id: str | None = None,
                    clarification_context: Mapping[str, Any] | None = None) -> tuple[dict, Any, dict]:
    clarification_context = _clarification_selection(frozen, clarification_context)
    state = _source_ledger(origin)["source_coverage"][key]
    old = state["binding"]
    anchor_state, ancestor_chain = await _commit_ancestor(backend, origin=origin, frozen=frozen, key=key,
        project_name=project_name, project_root=project_root)
    anchors = await _applied_anchors(backend, anchor_state, project_name, project_root)
    item = DreamItem(source_kind="knowledge_stale", source_id=key, proposed_action="replace",
                     final_action="applied", reason="Bound committed source anchor; not write authority.",
                     result={"truth_change": "replace", "truth_ids": anchors})
    shadow = {"target_ids": [key], "verification": {key: {"semantic_fingerprint": old["predecessor_sha256"]}}}
    prepared = await coverage._prepare(backend, project_name=project_name, project_root=project_root,
        run_id=run_id, item=item, checkpoint=shadow, notes=[], include_current_comparison=True)
    _require(prepared is not None, "source_unproved")
    for field in ("source_id", "source_revision", "source_job_id", "source_job_sha256", "context_sha256"):
        _require(prepared["binding"].get(field) == old.get(field), "original_context_changed")
    original_context_binding = {field: old[field] for field in (
        "source_id", "source_revision", "source_job_id", "source_job_sha256", "context_sha256")}
    original_context_binding.update(session_id=prepared["job"].session_id, client=prepared["job"].client,
        project_name=project_name, project_root_sha256=_digest(str(Path(project_root).resolve())))
    later_contexts, later_windows = await _later_user_contexts(backend, prepared,
        project_name=project_name, project_root=project_root, original_binding=original_context_binding,
        required_context_hashes={ref["context_sha256"]
            for window in (state.get("inventory_verification") or {}).get("windows") or []
            for span in window.get("spans") or [] for ref in span.get("r") or [] if "context_sha256" in ref})
    prepared["comparison_current_truth"] = await _project_comparisons(backend,
        project_name=project_name, project_root=project_root, successor_ids=anchors)
    old_rows = frozen["source_bindings"][key]["current_rows"]
    old_ids = sorted(old_rows)
    current = {row["id"]: row for row in [*prepared["successors"], *prepared["comparison_current_truth"]]}
    new_ids = sorted(current)
    unchanged = set()
    store = backend.structured_store.knowledge_store
    for identity in old_ids:
        if identity not in current:
            continue
        snapshot = {k: v for k, v in current[identity].items() if k not in {"comparison_only", "kind"}}
        refs = await store.list_sources(identity)
        if (_digest(snapshot) == old_rows[identity]["scope_sha256"]
                and _digest([ref.to_dict() for ref in refs]) == old_rows[identity]["sources_sha256"]):
            unchanged.add(identity)
    windows, votes = _audit_windows(state, prepared["authored_user_exchanges"], len(old_ids), later_windows)
    committed = await _committed_points(backend, state, prepared, new_ids)
    recovery_proof = None
    recovered = {}
    resolved_no_write = {}
    uncommitted_extracts = {point for window in windows for span in window["spans"]
                           if span["d"] == "extract" for point in span["p"] if point not in committed}
    observed = []
    budget_proof, budget_pending = None, []
    if state.get("status") == "failed" and state.get("reason_code") in _BUDGET_EXHAUSTION:
        account = read_task_budget_receipt(Path(backend.data_dir), _source_ledger(origin)["task_scope"])
        budget_proof = _budget_interruption(origin, state, frozen, account)
        source = {"contract": "source-coverage-inventory-v1",
            **{name: old[name] for name in ("source_id", "source_revision", "context_sha256")},
            "windows": [{**{k: v for k, v in row.items() if k != "anchor_sha256"},
                         "exchange_sha256": row["anchor_sha256"]} for row in prepared["authored_user_exchanges"]],
            "current": [current[identity] for identity in old_ids if identity in current]}
        if later_contexts:
            source["later_user_contexts"] = later_contexts
        budget_pending = await _budget_workspace(backend, origin, state, prepared, source, original_context_binding)
        _require(uncommitted_extracts <= {row["point_index"] for row in budget_pending}, "budget_points_incomplete")
    elif state["inventory_verification"].get("admission_mode") == "observation":
        observed = await _observed_workspace(backend, state, prepared)
        _require(uncommitted_extracts <= {row["point_index"] for row in observed}, "observed_points_incomplete")
    elif frozen.get("contract") == CONTRACT and uncommitted_extracts:
        _require(isinstance(resolved_handoff_run_id, str) and bool(resolved_handoff_run_id),
                 "handoff_recovery_required")
        recovered, recovery_proof, resolved_no_write = await _recovered_points(backend, origin=origin, state=state,
            prepared=prepared, new_ids=new_ids, recovery_run_id=resolved_handoff_run_id)
        _require(uncommitted_extracts <= set(recovered) | set(resolved_no_write), "handoff_recovery_incomplete")
        committed.update(recovered)
    ancestor_committed = (await _committed_points(backend, anchor_state, prepared, new_ids)
                          if ancestor_chain else {})
    if ancestor_chain:
        # An audit child's zero writes remain zero. These bind its previously
        # converted covered spans, not indexes in this child's candidate list.
        _require(ancestor_committed, "ancestor_commit_unproved")
    pending, retained, protected = [], [], []
    for window in windows:
        w = window["w"]
        for index, span in enumerate(window["spans"]):
            vote = votes[(w, index)]
            linked = [old_ids[value] for value in span["c"]]
            covered_points = [point for point in span["p"] if point in committed]
            if covered_points:
                _require(span["d"] == "extract" and vote["verdict"] == "supported"
                         and covered_points == span["p"], "committed_span_mixed_or_unverified")
                _require(all(prepared["authored_user_exchanges"][w]["exchange_index"]
                             in committed[point]["source_exchange_indexes"] for point in covered_points),
                         "committed_span_source_mismatch")
                truth = {}
                for point in covered_points:
                    for row in committed[point]["truth_bindings"]:
                        truth[row["id"]] = row
                bindings = list(truth.values())
                converted = {"w": w, "span_index": index, "s": span["s"], "e": span["e"],
                    "original_point_indexes": list(span["p"]),
                    "candidate_ids": [committed[point]["candidate_id"] for point in covered_points],
                    "truth_ids": list(truth), "truth_bindings": bindings,
                    "commit_bindings": [commit for point in covered_points for commit in (
                        committed[point]["commit_bindings"] if "commit_bindings" in committed[point]
                        else [committed[point]["commit"]])]}
                if any(point in recovered for point in covered_points):
                    _require(all(point in recovered for point in covered_points), "recovery_span_mixed")
                    converted.update(writing_candidate_ids=[recovered[point]["writing_candidate_id"]
                        for point in covered_points], recovery_run_id=resolved_handoff_run_id,
                        recovery_proof_sha256=_digest(recovery_proof))
                converted["basis_sha256"] = _digest(converted)
                protected.append(converted)
                retained.append({"w": w, "span_index": index,
                    "span": {"s": span["s"], "e": span["e"], "d": "covered", "p": [], "r": [],
                             "c": [row["current_index"] for row in bindings]},
                    "basis_sha256": converted["basis_sha256"]})
                continue
            if (vote["verdict"] != "supported" or span["d"] in {"extract", "unclear"}
                    or any(identity not in unchanged for identity in linked)):
                pending.append({"w": w, "span_index": index, "s": span["s"], "e": span["e"]})
                continue
            mapped = {**span, "c": [new_ids.index(identity) for identity in linked]}
            basis = {"origin_state_sha256": _digest(state), "vote": vote, "span": span,
                     "window_sha256": prepared["authored_user_exchanges"][w]["sha256"],
                     "current": {identity: old_rows[identity] for identity in linked}}
            retained.append({"w": w, "span_index": index, "span": mapped, "basis_sha256": _digest(basis)})
    deferred = [] if budget_proof is not None else await _deferred_workspace(backend, state,
        resolved_candidate_ids=[row["candidate_id"] for row in [*recovered.values(), *resolved_no_write.values()]])
    repair = {"contract": RESIDUAL_CONTRACT, "origin_run_id": origin.id, "origin_state_key": key,
              "task_scope": _source_ledger(origin)["task_scope"],
              "origin_state_sha256": _digest(state),
              "origin_inventory_input_sha256": state["inventory_verification"]["input_sha256"],
              "origin_windows": windows, "origin_audit": state["inventory_verification"]["audit"],
              "pending_spans": pending, "retained_spans": retained,
              "committed_point_spans": protected,
              "committed_candidate_bindings": [{key: value for key, value in row.items()
                  if key != "source_exchange_indexes"} for row in committed.values()],
              "original_context_binding": original_context_binding,
              "already_applied_truth_ids": list(dict.fromkeys([*anchors, *[
                  truth["id"] for row in recovered.values() for truth in row["truth_bindings"]]])),
              "origin_candidate_ids": list(state.get("candidate_ids") or []),
              "origin_candidate_outcomes": deepcopy(state.get("candidate_outcomes") or []),
              "deferred_workspace_bindings": deferred}
    if ancestor_chain:
        repair["ancestor_source_bindings"] = ancestor_chain
        repair["ancestor_committed_candidate_bindings"] = [{name: value for name, value in row.items()
            if name != "source_exchange_indexes"} for row in ancestor_committed.values()]
    if observed:
        repair["observed_candidate_bindings"] = observed
    if budget_proof is not None:
        repair["budget_interruption"] = budget_proof
        repair["budget_interrupted_candidate_bindings"] = budget_pending
    if recovery_proof is not None:
        repair["resolved_handoff_proof"] = recovery_proof
        repair["resolved_handoff_proof_sha256"] = _digest(recovery_proof)
    if resolved_no_write:
        repair["resolved_no_write_points"] = [resolved_no_write[index] for index in sorted(resolved_no_write)]
    if later_contexts:
        repair["later_user_contexts"] = later_contexts
    if clarification_context is not None:
        selections = _clarification_selections(clarification_context)
        previous = _clarification_selections(frozen.get("clarification_context"))
        contexts = [_clarification_context(backend, prepared, repair, selected, inherited=index < len(previous))
                    for index, selected in enumerate(selections)]
        repair["clarification_context"] = ({"contexts": contexts}
            if "selections" in clarification_context else contexts[0])
    repair["reuse_binding_sha256"] = _digest(repair)
    prepared["inventory_audit_repair"] = repair
    snapshots, entries = await coverage._explicit_current_rows(backend, prepared,
        project_name=project_name, project_root=project_root)
    prepared["successor_entries"] = entries
    return prepared, item, snapshots


_OBSERVATION_CONTRACT = "source-coverage-failed-observation-v1"
_OBSERVATION_FIELDS = ("inventory_verification", "inventory_workspace", "inventory_observation")


def _validate_observation_witness(payload: dict, key: str, account: dict) -> dict:
    """Check an appended observation without forgiving any historical failure."""
    from harness_mem.autonomous.executors.task_budget import _closed_allowance_calls, effective_task_budget_bounds
    from harness_mem.autonomous.provider import source_coverage_audit_has_unresolved

    state = payload["continuation"]["source_inventory_audit"]["source_coverage"][key]
    proof = state.get("inventory_observation") or {}
    _require(proof.get("contract") == _OBSERVATION_CONTRACT
             and proof.get("run_id") == payload["id"] and proof.get("predecessor_id") == key
             and proof.get("binding_sha256") == state.get("binding_sha256")
             and proof.get("proof_sha256") == _digest({k: v for k, v in proof.items() if k != "proof_sha256"}),
             "observation_proof_invalid")
    before = deepcopy(payload)
    before_state = before["continuation"]["source_inventory_audit"]["source_coverage"][key]
    for name in _OBSERVATION_FIELDS:
        before_state.pop(name, None)
    _require(_digest(before) == proof.get("before_payload_logical_sha256")
             and _raw_digest(json.dumps(before, sort_keys=True, ensure_ascii=True,
                                        separators=(",", ":"), default=str)) == proof.get("before_payload_sha256")
             and _digest(before_state) == proof.get("before_state_sha256")
             and state.get("status") == "failed" and not state.get("candidate_ids")
             and not state.get("commit_bindings") and not state.get("committed_candidate_ids"),
             "observation_original_changed")
    summary = state.get("inventory_verification") or {}
    _require(summary.get("admission_mode") == "observation"
             and summary.get("summary_sha256") == proof.get("summary_sha256")
             and source_coverage_audit_has_unresolved(summary)
             and state.get("inventory_workspace") == {"input_sha256": summary["input_sha256"], "workspace": []},
             "observation_summary_changed")
    count, grants = proof.get("account_prefix_count"), proof.get("allowance_prefix_count")
    calls, allowances = account.get("calls"), account.get("allowance_grants", [])
    _require(type(count) is int and count > 0 and isinstance(calls, list) and len(calls) >= count
             and type(grants) is int and grants >= 0 and isinstance(allowances, list) and len(allowances) >= grants
             and account.get("task_scope") == proof.get("task_scope")
             and account.get("host_client") == proof.get("host_client")
             and _digest(account.get("bounds")) == proof.get("bounds_sha256")
             and _digest(calls[:count]) == proof.get("account_prefix_sha256")
             and _digest(allowances[:grants]) == proof.get("allowance_prefix_sha256"),
             "observation_account_changed")
    _closed_allowance_calls(calls)
    effective_task_budget_bounds(account)
    receipts = _observation_receipts(payload, state)
    _require(_digest(receipts) == proof.get("native_receipts_sha256"), "observation_receipt_changed")
    return proof


def _observation_receipts(payload: dict, state: dict) -> list[dict]:
    prefix = "dream source coverage receipt: "
    rows = []
    seen = {}
    for note in [*(payload.get("notes") or []),
                 *(payload["continuation"].get("terminal_coverage_receipts") or [])]:
        if isinstance(note, str) and note.startswith(prefix):
            receipt = json.loads(note[len(prefix):])
            if receipt.get("attempt_id") == state["binding_sha256"]:
                phase = receipt.get("phase")
                _require(phase not in seen or seen[phase] == receipt, "observation_receipt_conflict")
                if phase in seen:
                    continue
                seen[phase] = receipt
                rows.append(receipt)
    return rows


async def settle_failed_source_audit_observation(backend: Any, *, project_name: str,
        project_root: str | Path, run_id: str, predecessor_id: str,
        expected_payload_sha256: str, manifest: dict, raw_response: str | bytes) -> dict:
    """Append a complete negative native audit; never replay or approve a write."""
    from harness_mem.autonomous.executors.task_budget import (
        _closed_allowance_calls, _receipt_lock, effective_task_budget_bounds, task_budget_receipt_path,
    )
    from harness_mem.autonomous.models import NativeSourceCoverageVerificationDecision
    from harness_mem.autonomous.provider import (
        _bound_coverage_inventory, _build_verification_prompt,
        expand_source_coverage_verification_decision, get_source_coverage_audit_observation,
    )
    from harness_mem.autonomous.worker import _build_candidate_verification_manifest

    canonical = backend.structured_store._canonical
    raw = canonical.get_payload_json("dream_runs", run_id)
    _require(raw is not None, "observation_run_missing")
    payload = json.loads(raw)
    run = await backend.structured_store.get_dream_run(run_id)
    _require(run is not None and _digest(run.to_dict()) == _digest(payload)
             and run.project_name == project_name and run.status == "failed"
             and run.trigger_source == "agent" and run.completed_at is not None, "observation_run_invalid")
    frozen = (run.continuation.get("explicit_repair_scope") or {}).get("source") or {}
    ledger = run.continuation.get("source_inventory_audit") or {}
    state = (ledger.get("source_coverage") or {}).get(predecessor_id) or {}
    _require(frozen.get("contract") == CONTRACT and frozen.get("run_id") == run_id
             and frozen.get("project_name") == project_name
             and frozen.get("project_root_sha256") == _digest(str(Path(project_root).resolve()))
             and ledger.get("manifest_sha256") == _digest(frozen)
             and state.get("status") == "failed"
             and state.get("reason_code") == "source_coverage_inventory_audit_unresolved"
             and state.get("binding_sha256") == _digest(state.get("binding"))
             and state.get("binding") == (frozen.get("source_bindings", {}).get(predecessor_id) or {}).get("binding")
             and not state.get("candidate_ids") and not state.get("committed_candidate_ids")
             and not state.get("commit_bindings"), "observation_state_invalid")
    old_proof = state.get("inventory_observation")
    _require((old_proof and old_proof.get("before_payload_sha256") == expected_payload_sha256)
             or (not old_proof and _raw_digest(raw) == expected_payload_sha256
                 and not any(name in state for name in _OBSERVATION_FIELDS)), "observation_cas_changed")
    account = read_task_budget_receipt(Path(backend.data_dir), ledger.get("task_scope", ""))
    maintenance = run.continuation.get("maintenance_scope") or {}
    _require(isinstance(account, dict) and account.get("task_scope") == ledger.get("task_scope")
             == frozen.get("task_scope") == maintenance_task_scope(
                 maintenance.get("trigger_id", ""), maintenance.get("dispatch_generation", ""))
             and account.get("host_client") == frozen.get("host_client"), "observation_account_missing")
    _closed_allowance_calls(account["calls"])
    effective_task_budget_bounds(account)
    if old_proof:
        _validate_observation_witness(payload, predecessor_id, account)
    origin, parent_frozen, _ = await _origin(backend, project_name=project_name, project_root=project_root,
        origin_run_id=frozen["origin_run_id"], run_id=run_id, predecessor_ids=[predecessor_id])
    parent_raw = canonical.get_payload_json("dream_runs", origin.id)
    _require(parent_raw is not None and _raw_digest(parent_raw) == frozen["origin_payload_sha256"],
             "observation_parent_changed")
    prepared, _item, snapshots = await _prepared(backend, origin=origin, frozen=parent_frozen,
        key=predecessor_id, project_name=project_name, project_root=project_root, run_id=run_id,
        resolved_handoff_run_id=frozen.get("resolved_handoff_run_id"))
    _require(prepared["job"].session_id != maintenance.get("trigger_id")
             and not state.get("candidate_outcomes"), "observation_legacy_explicit_scope_required")
    expected = frozen["source_bindings"][predecessor_id]
    _require(prepared["binding"] == expected["binding"] and snapshots == expected["current_rows"]
             and _digest(prepared["inventory_audit_repair"]) == expected["residual_sha256"],
             "observation_reopened_input_changed")
    source, inventory = _bound_coverage_inventory(manifest)
    comparison = {row["id"]: row for row in [*prepared["successors"], *prepared["comparison_current_truth"]]}
    expected_source = {"contract": "source-coverage-inventory-v1",
        **{name: prepared["binding"][name] for name in ("source_id", "source_revision", "context_sha256")},
        "windows": [{**{k: v for k, v in row.items() if k != "anchor_sha256"},
                     "exchange_sha256": row["anchor_sha256"]} for row in prepared["authored_user_exchanges"]],
        "current": [comparison[key] for key in sorted(comparison)]}
    later = prepared["inventory_audit_repair"].get("later_user_contexts")
    if later:
        expected_source["later_user_contexts"] = later
    _require(source == expected_source and not inventory["extracted_points"]
             and manifest["source_coverage"].get("inventory_audit_repair") == prepared["inventory_audit_repair"],
             "observation_manifest_changed")
    base = _build_candidate_verification_manifest(packet=prepared["packet"], validated_candidates=[],
        project_root=project_root, backend=backend, distill_job_id=prepared["job"].id)
    expected_manifest = {**base, "source_coverage": manifest["source_coverage"], "session_context": [
        {"kind": "runtime_maintenance_scope_not_source_evidence", "content": json.dumps(
            manifest["source_coverage"], ensure_ascii=False, sort_keys=True)}, *(base.get("session_context") or [])]}
    _require(manifest == expected_manifest, "observation_complete_context_changed")
    response = raw_response.decode("utf-8") if isinstance(raw_response, bytes) else raw_response
    _require(isinstance(response, str), "observation_response_invalid")
    native = NativeSourceCoverageVerificationDecision.model_validate_json(response)
    _require(not native.points, "observation_points_not_empty")
    decision = expand_source_coverage_verification_decision(native, manifest=manifest)
    summary = get_source_coverage_audit_observation(decision, manifest)
    receipts = _observation_receipts(payload, state)
    matches = [row for row in receipts if row.get("phase") == "candidate_verify"
        and row.get("input_sha256") == _raw_digest(_build_verification_prompt(manifest))
        and row.get("response_sha256") == _raw_digest(response)
        and row.get("source_job_id") == prepared["job"].id and row.get("schema_valid") is True]
    _require(len(matches) == 1, "observation_native_receipt_missing")
    receipt = matches[0]
    calls = [row for row in account["calls"] if row.get("phase") == "dream" and row.get("slice_id")
        == f"source-coverage:{run_id}:{state['binding_sha256']}:source-verify"]
    _require(len(calls) == 1 and calls[0].get("status") == "completed"
             and calls[0].get("model_completion") is True
             and calls[0]["usage"]["input_tokens"] == receipt.get("input_tokens")
             and calls[0]["usage"]["output_tokens"] == receipt.get("output_tokens")
             and abs(calls[0]["usage"]["duration_seconds"] - receipt.get("duration_seconds", -100)) < .01,
             "observation_native_account_changed")
    workspace = {"input_sha256": summary["input_sha256"], "workspace": []}
    if old_proof:
        _require(state["inventory_verification"] == summary and state["inventory_workspace"] == workspace,
                 "observation_replay_changed")
        return _observation_result(run_id, expected_payload_sha256, _raw_digest(raw), summary, replayed=True)
    proof = {"contract": _OBSERVATION_CONTRACT, "run_id": run_id, "predecessor_id": predecessor_id,
        "binding_sha256": state["binding_sha256"], "before_payload_sha256": expected_payload_sha256,
        "before_payload_logical_sha256": _digest(payload), "before_state_sha256": _digest(state),
        "task_scope": account["task_scope"], "host_client": account["host_client"],
        "bounds_sha256": _digest(account["bounds"]), "account_prefix_count": len(account["calls"]),
        "account_prefix_sha256": _digest(account["calls"]),
        "allowance_prefix_count": len(account.get("allowance_grants", [])),
        "allowance_prefix_sha256": _digest(account.get("allowance_grants", [])),
        "native_receipts_sha256": _digest(receipts), "summary_sha256": summary["summary_sha256"]}
    proof["proof_sha256"] = _digest(proof)
    state.update(inventory_verification=summary, inventory_workspace=workspace, inventory_observation=proof)
    updated = deepcopy(payload)
    updated["continuation"]["source_inventory_audit"]["source_coverage"][predecessor_id] = state
    mutations = [{"operation": "upsert", "collection": "dream_runs", "project_name": project_name,
        "entity_id": run_id, "payload": updated, "expected_sha256": expected_payload_sha256},
        {"operation": "assert", "collection": "dream_runs", "project_name": project_name,
         "entity_id": origin.id, "expected_sha256": _raw_digest(parent_raw)}]
    for identity in snapshots:
        refs = await backend.structured_store.knowledge_store.list_sources(identity)
        row = canonical.get_row("knowledge_entries", identity, project_name=project_name)
        _require(row is not None and _digest(json.loads(row.payload_json)) == snapshots[identity]["payload_sha256"]
                 and _digest([ref.to_dict() for ref in refs]) == snapshots[identity]["sources_sha256"],
                 "observation_current_changed")
        mutations.append({"operation": "assert", "collection": "knowledge_entries", "project_name": project_name,
            "entity_id": identity, "expected_sha256": row.payload_sha256,
            "expected_source_ids": sorted(ref.id for ref in refs)})
        for ref in refs:
            row = canonical.get_row("knowledge_sources", ref.id, project_name=project_name)
            _require(row is not None and _digest(json.loads(row.payload_json)) == _digest(ref.to_dict()),
                     "observation_current_source_changed")
            mutations.append({"operation": "assert", "collection": "knowledge_sources", "project_name": project_name,
                "entity_id": ref.id, "expected_sha256": row.payload_sha256})
    with _receipt_lock(task_budget_receipt_path(Path(backend.data_dir), account["task_scope"])):
        _require(read_task_budget_receipt(Path(backend.data_dir), account["task_scope"]) == account,
                 "observation_account_raced")
        current_job = backend.transcript_store.get_distill_job(prepared["job"].id)
        _require(current_job is not None and _digest(current_job.to_dict()) == prepared["binding"]["source_job_sha256"],
                 "observation_source_job_raced")
        for child in canonical.list_payloads("dream_runs", project_name=project_name):
            if child.get("id") == run_id:
                continue
            continuation = child.get("continuation") or {}
            child_source = (continuation.get("explicit_repair_scope") or {}).get("source") or {}
            recovery = (continuation.get("source_handoff_recovery_scope") or {}).get("binding") or {}
            _require(not (child_source.get("origin_run_id") == run_id
                          and child_source.get("origin_payload_sha256") == expected_payload_sha256)
                     and not (recovery.get("origin_run_id") == run_id), "observation_descendant_exists")
        # Before this CAS the failed leaf has no admissible inventory, so the
        # source-audit owner cannot freeze a legitimate descendant from its old
        # SHA. This is an owner-bound check, not an atomic collection predicate
        # against direct SQLite writers. The caller retains the project lease.
        canonical.apply_payload_transaction(idempotency_key="source-audit-observation:" + proof["proof_sha256"],
            mutations=mutations)
    after = canonical.get_payload_json("dream_runs", run_id)
    return _observation_result(run_id, expected_payload_sha256, _raw_digest(after), summary, replayed=False)


def _observation_result(run_id: str, before: str, after: str, summary: dict, *, replayed: bool) -> dict:
    dispositions = {(window["w"], index): span["d"] for window in summary["windows"]
                    for index, span in enumerate(window["spans"])}
    pending = sum(row["verdict"] != "supported" or dispositions[(row["w"], row["span_index"])] == "unclear"
                  for row in summary["audit"])
    return {"run_id": run_id, "before_payload_sha256": before, "after_payload_sha256": after,
            "replayed": replayed, "inventory_verification": summary,
            "inventory_span_count": len(dispositions), "retained_span_count": len(dispositions) - pending,
            "pending_span_count": pending}


async def prepare_explicit_source_audit(backend: Any, *, project_name: str,
        project_root: str | Path, run_id: str, origin_run_id: str,
        predecessor_ids: Sequence[str], resolved_handoff_run_id: str | None = None,
        clarification_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Freeze only residual work from a failed explicit inventory checkpoint."""
    origin, frozen, account = await _origin(backend, project_name=project_name, project_root=project_root,
        origin_run_id=origin_run_id, run_id=run_id, predecessor_ids=predecessor_ids)
    clarification_context = _clarification_selection(frozen, clarification_context)
    _require(clarification_context is None or len(predecessor_ids) == 1, "clarification_selection_ambiguous")
    source_bindings = {}
    for key in predecessor_ids:
        prepared, _item, snapshots = await _prepared(backend, origin=origin, frozen=frozen, key=key,
            project_name=project_name, project_root=project_root, run_id=run_id,
            resolved_handoff_run_id=resolved_handoff_run_id, clarification_context=clarification_context)
        source_bindings[key] = {"binding": prepared["binding"],
            "residual_sha256": _digest(prepared["inventory_audit_repair"]), "current_rows": snapshots}
        recovered = prepared["inventory_audit_repair"].get("resolved_handoff_proof")
        if recovered is not None:
            source_bindings[key]["resolved_handoff_binding"] = {"run_id": recovered["recovery_run_id"],
                "payload_sha256": recovered["payload_sha256"], "proof_sha256": _digest(recovered)}
    raw = backend.structured_store._canonical.get_payload_json("dream_runs", origin.id)
    _require(raw is not None and _digest(json.loads(raw)) == _digest(origin.to_dict()), "origin_changed")
    manifest = {"contract": CONTRACT, "project_name": project_name,
            "project_root_sha256": _digest(str(Path(project_root).resolve())), "run_id": run_id,
            "origin_run_id": origin.id, "origin_payload_sha256": _raw_digest(raw),
            "task_scope": account["task_scope"], "host_client": account["host_client"],
            "account_prefix_count": len(account["calls"]), "account_prefix_sha256": _digest(account["calls"]),
            "predecessor_ids": list(predecessor_ids), "source_bindings": source_bindings}
    if clarification_context is not None:
        manifest["clarification_context"] = deepcopy(dict(clarification_context))
    if resolved_handoff_run_id is not None:
        _require(isinstance(resolved_handoff_run_id, str) and bool(resolved_handoff_run_id),
                 "handoff_recovery_selection_invalid")
        manifest["resolved_handoff_run_id"] = resolved_handoff_run_id
    return manifest


async def run_explicit_source_audit(backend: Any, *, project_name: str,
        project_root: str | Path, run_id: str, manifest: dict[str, Any],
        checkpoint: dict[str, Any], notes: list[str], provider: Any,
        persist: Callable[[], Awaitable[None]],
        boundary: Callable[[], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Use the existing coverage worker and persistence owner on a new child."""
    _require(manifest.get("contract") == CONTRACT and manifest.get("run_id") == run_id
             and manifest.get("project_name") == project_name
             and manifest.get("project_root_sha256") == _digest(str(Path(project_root).resolve())), "manifest_changed")
    binding = getattr(provider, "task_budget_binding", None)
    _require(binding is not None and binding.task_scope == manifest.get("task_scope")
             and binding.host_client == manifest.get("host_client")
             and getattr(provider, "host_client", None) == binding.host_client
             and Path(binding.data_dir).resolve() == Path(backend.data_dir).resolve(), "same_account_required")
    keys = manifest.get("predecessor_ids") or []
    _require(keys and set(keys) == set(manifest.get("source_bindings") or {}), "selection_changed")
    state = checkpoint.setdefault("source_inventory_audit", {
        "contract": CONTRACT, "manifest_sha256": _digest(manifest),
        "task_scope": binding.task_scope, "source_coverage": {}})
    _require(state.get("manifest_sha256") == _digest(manifest)
             and state.get("task_scope") == binding.task_scope, "attempt_changed")
    origin, frozen, _account = await _origin(backend, project_name=project_name, project_root=project_root,
        origin_run_id=manifest["origin_run_id"], run_id=run_id, predecessor_ids=keys)
    items = []
    for key in keys:
        items.append(DreamItem(source_kind="knowledge_stale", source_id=key, proposed_action="replace",
            final_action="applied", reason="Bound committed source anchor; not write authority.",
            result={"truth_change": "replace", "truth_ids": manifest["source_bindings"][key]["binding"]["successor_ids"]}))
    shadow = {"target_ids": list(keys), "slice_count": checkpoint.get("slice_count", 1),
              "verification": {key: {"semantic_fingerprint":
                  frozen["source_bindings"][key]["binding"]["predecessor_sha256"]} for key in keys},
              "source_coverage": state["source_coverage"]}

    async def validate() -> None:
        raw = backend.structured_store._canonical.get_payload_json("dream_runs", manifest["origin_run_id"])
        _require(raw is not None and _raw_digest(raw) == manifest["origin_payload_sha256"], "origin_changed")
        _require(getattr(provider, "task_budget_binding", None) is binding, "account_binding_changed")
        account = read_task_budget_receipt(Path(backend.data_dir), binding.task_scope)
        count = manifest["account_prefix_count"]
        _require(isinstance(account, dict) and account.get("task_scope") == binding.task_scope
                 and account.get("host_client") == binding.host_client
                 and len(account.get("calls") or []) >= count
                 and _digest(account["calls"][:count]) == manifest["account_prefix_sha256"], "account_history_changed")
        store = backend.structured_store.knowledge_store
        for key in keys:
            frozen_source = manifest["source_bindings"][key]
            recovery = frozen_source.get("resolved_handoff_binding")
            if recovery is not None:
                raw = backend.structured_store._canonical.get_payload_json("dream_runs", recovery["run_id"])
                _require(raw is not None and _raw_digest(raw) == recovery["payload_sha256"],
                         "recovery_carrier_changed")
            job = backend.transcript_store.get_distill_job(frozen_source["binding"]["source_job_id"])
            _require(job is not None and _digest(job.to_dict()) == frozen_source["binding"]["source_job_sha256"],
                     "source_job_changed")
            for identity, expected in frozen_source["current_rows"].items():
                entry = await store.get_entry(identity, project_name=project_name, project_root=project_root)
                refs = await store.list_sources(identity)
                _require(entry is not None and _digest(entry.to_dict()) == expected["payload_sha256"]
                         and _digest([ref.to_dict() for ref in refs]) == expected["sources_sha256"], "current_changed")

    async def guard(prepared: dict[str, Any]) -> None:
        await validate()
        key = prepared["binding"]["predecessor_id"]
        rebuilt, _item, snapshots = await _prepared(backend, origin=origin, frozen=frozen, key=key,
            project_name=project_name, project_root=project_root, run_id=run_id,
            resolved_handoff_run_id=manifest.get("resolved_handoff_run_id"),
            clarification_context=manifest.get("clarification_context"))
        expected = manifest["source_bindings"][key]
        _require(prepared["binding"] == expected["binding"]
                 and rebuilt["binding"] == expected["binding"]
                 and _digest(rebuilt["inventory_audit_repair"]) == expected["residual_sha256"]
                 and snapshots == expected["current_rows"], "prepared_changed")
        prepared["inventory_audit_repair"] = rebuilt["inventory_audit_repair"]
        prepared["successor_entries"] = rebuilt["successor_entries"]
        prepared["successors"] = rebuilt["successors"]
        prepared["comparison_current_truth"] = rebuilt["comparison_current_truth"]

    async def save() -> None:
        await validate()
        state["source_coverage"] = shadow["source_coverage"]
        await persist()

    await validate()
    worked = await coverage.run_applied_source_coverage(backend, project_name=project_name,
        project_root=project_root, run_id=run_id, checkpoint=shadow, notes=notes,
        items=items, provider=provider, persist=save, boundary=boundary, prepare_guard=guard)
    statuses = [(state["source_coverage"].get(key) or {}).get("status") for key in keys]
    pending = any(value not in _TERMINAL for value in statuses)
    return {"worked": worked, "pending": pending,
            "status": "pending" if pending else "applied" if all(value == "applied" for value in statuses)
            else "no_write" if all(value in {"applied", "no_write", "not_applicable"} for value in statuses)
            else "unresolved"}
