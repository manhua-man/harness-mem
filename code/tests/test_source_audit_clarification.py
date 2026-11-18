"""Proposed fixtures for explicit clarification; no real model or installed data."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from test_residual_source_audit import captured as captured, coverage as coverage
from test_residual_source_audit import terminal as terminal, residual as residual, run, invoke
from test_residual_source_audit import audit_child, seal_audit
from test_residual_source_audit_transport import residual as transport_residual, verify_manifest
from harness_mem.adapters.snapshot import _native_codex_authored_texts, persist_session_snapshot
from harness_mem.autonomous import provider
from harness_mem.autonomous.models import NativeResidualSourceCoverageExtractionDecision
from harness_mem.commands import dream_source_audit as owner
from harness_mem.commands import dream_source_coverage as original
from harness_mem.commands.session_inventory import session_reference
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.observation import Observation


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def reseal(repair):
    repair["reuse_binding_sha256"] = provider._coverage_digest({
        key: value for key, value in repair.items() if key != "reuse_binding_sha256"})


@pytest.fixture
def clarification(residual):
    data = residual
    job = data["prepared"]["job"]
    # Keep the complete question inside the original captured reply itself.
    reply = json.dumps({"question": "Was the old verification request a lasting requirement?",
                        "answer": "Only test it then; it was not a lasting requirement."})
    records = [{"type": "session_meta", "payload": {"id": job.session_id, "cwd": str(data["root"])}}]
    for index, (role, content) in enumerate((("user", "Earlier full user context."),
            ("assistant", "Contextual question, not approval."), ("user", reply))):
        records.append({"type": "response_item", "payload": {"type": "message", "turn_id": str(index),
            "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": content}]}})
    native = ("\n".join(json.dumps(row) for row in records) + "\n").encode()
    rendering = _native_codex_authored_texts(native)[0]
    snapshot = run(persist_session_snapshot(data["backend"], Observation(session_id=job.session_id,
        client=job.client, raw_content=rendering, content_type="transcript", timestamp=datetime.now(timezone.utc),
        metadata={}), project_name="demo", project_root=str(data["root"]), client=job.client,
        session_id=job.session_id, source_kind="jsonl", source_uri=(data["root"] / "clarification.jsonl").as_uri(),
        source_text=rendering, raw_bytes=rendering.encode(), native_input_bytes=native,
        parser_version="codex-conversation-v3", capture_config=MergedConfig()))
    row = data["prepared"]["authored_user_exchanges"][1]
    selection = {"source_ref": session_reference(job.client, job.session_id, snapshot.source.id,
                    snapshot.source.source_revision),
        "reply": {"exchange_index": 2, "message_index": 0, "sha256": sha(reply)},
        "target": {"source_id": data["prepared"]["binding"]["source_id"],
            "source_revision": data["prepared"]["binding"]["source_revision"],
            "w": 1, "span_index": 0, "s": 0, "e": len(row["text"]), "sha256": row["sha256"]}}
    return {**data, "selection": selection, "reply": reply, "snapshot": snapshot}


def prepare(data):
    return run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="residual-run", origin_run_id=data["origin"].id,
        predecessor_ids=[data["key"]], clarification_context=data["selection"]))


def rebuilt(data):
    return run(owner._prepared(data["backend"], origin=data["origin"], frozen=data["frozen"], key=data["key"],
        project_name="demo", project_root=data["root"], run_id="residual-run",
        clarification_context=data["selection"]))[0]


def test_real_complete_user_context_retains_question_and_original_identity(clarification):
    data = clarification
    baseline = run(owner._prepared(data["backend"], origin=data["origin"], frozen=data["frozen"], key=data["key"],
        project_name="demo", project_root=data["root"], run_id="residual-run"))[0]
    manifest = prepare(data)
    prepared = rebuilt(data)
    repair = prepared["inventory_audit_repair"]
    packet = repair["clarification_context"]
    body = json.loads(packet["content"])
    assert body["role"] == "user" and len(body["authored_exchanges"]) == 2
    assert body["authored_exchanges"][0]["messages"] == ["Earlier full user context."]
    assert body["authored_exchanges"][1]["messages"] == [data["reply"]]
    assert "question" in body["authored_exchanges"][1]["messages"][0]
    assert packet["selection"] == data["selection"] and packet["context_sha256"] == sha(packet["content"])
    assert manifest["clarification_context"] == data["selection"]
    assert manifest["task_scope"] == data["binding"].task_scope
    for key in ("authored_user_exchanges", "binding"):
        assert prepared[key] == baseline[key]
    for key in ("pending_spans", "retained_spans", "origin_windows", "original_context_binding", "later_user_contexts"):
        assert repair.get(key) == baseline["inventory_audit_repair"].get(key)
    assert manifest["source_bindings"][data["key"]]["residual_sha256"] == owner._digest(repair)


@pytest.mark.parametrize("fault", ["source_ref", "revision", "session", "reply_sha", "reply_index",
                                   "target_sha", "target_range", "target_source", "target_retained", "extra"])
def test_explicit_selection_drift_refuses_before_native(clarification, fault):
    data = clarification
    selected = data["selection"]
    if fault == "source_ref":
        selected["source_ref"]["reference_id"] = "f" * 64
    elif fault == "revision":
        selected["source_ref"]["source_revision"] = "sha256:" + "f" * 64
    elif fault == "session":
        selected["source_ref"]["session_id"] = "foreign-session"
    elif fault == "reply_sha":
        selected["reply"]["sha256"] = "f" * 64
    elif fault == "reply_index":
        selected["reply"]["message_index"] = 99
    elif fault == "target_sha":
        selected["target"]["sha256"] = "f" * 64
    elif fault == "target_range":
        selected["target"]["s"] += 1
    elif fault == "target_source":
        selected["target"]["source_id"] = selected["source_ref"]["source_id"]
    elif fault == "target_retained":
        selected["target"]["w"] = 0
    else:
        selected["unexpected"] = True
    with pytest.raises(ValueError):
        prepare(data)
    assert data["provider"].calls == []


@pytest.mark.parametrize("fault", ["raw", "user_proof", "truncated"])
def test_complete_reopen_and_role_proof_are_mandatory(clarification, monkeypatch, fault):
    data = clarification
    if fault == "raw":
        ledger = data["backend"].transcript_store
        reopen = ledger.reconstruct_raw
        monkeypatch.setattr(ledger, "reconstruct_raw", lambda *args, **kwargs: reopen(*args, **kwargs) + b"changed")
    else:
        reopen = original._reopen_complete_user_context
        def altered(*args, **kwargs):
            status, reason, content, truncated, effective = reopen(*args, **kwargs)
            return ("unverified" if fault == "user_proof" else status, reason, content,
                    fault == "truncated" or truncated, effective)
        monkeypatch.setattr(original, "_reopen_complete_user_context", altered)
    with pytest.raises(ValueError):
        prepare(data)
    assert data["provider"].calls == []


def test_run_guard_reopens_identical_frozen_clarification_before_worker(clarification, monkeypatch):
    data = clarification
    manifest = prepare(data)
    reopen = owner._clarification_context
    def changed(*args, **kwargs):
        packet = reopen(*args, **kwargs)
        packet["raw_sha256"] = "e" * 64
        return packet
    monkeypatch.setattr(owner, "_clarification_context", changed)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt",
                        lambda *_args, **_kwargs: pytest.fail("worker must not start"))
    # The coverage owner retains this failed guard as unresolved, without native work.
    result = invoke(data, manifest)
    assert result["status"] == "unresolved" and data["provider"].calls == []


def transport():
    manifest, payload = transport_residual()
    source = manifest["source_coverage"]["inventory_input"]
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    repair["original_context_binding"].update(session_id="session", client="codex", project_name="demo")
    reply = json.dumps({"question": "Was the earlier request permanent?", "answer": "Only test it then."})
    ref = session_reference("codex", "session", "separate-source", "sha256:" + "d" * 64)
    content = json.dumps({"context_scope": "complete-authored-user-v1", "role": "user", "project_name": "demo",
        "source_id": ref["source_id"], "source_revision": ref["source_revision"], "session_id": "session",
        "authored_exchanges": [{"exchange_index": 1, "messages": ["Earlier context."]},
                               {"exchange_index": 2, "messages": [reply]}]})
    repair["clarification_context"] = {"contract": "source-coverage-clarification-v1", "content": content,
        "context_sha256": sha(content), "raw_sha256": "d" * 64, "rendering_sha256": "e" * 64,
        "reply_exchange_sha256": "f" * 64, "selection": {"source_ref": ref,
            "reply": {"exchange_index": 2, "message_index": 0, "sha256": sha(reply)},
            "target": {"source_id": source["source_id"], "source_revision": source["source_revision"],
                "sha256": source["windows"][0]["sha256"], **repair["pending_spans"][0]}}}
    reseal(repair)
    return manifest, payload


def test_both_native_prompts_receive_complete_context_without_changing_original_indexes():
    manifest, payload = transport()
    source = deepcopy(manifest["source_coverage"]["inventory_input"])
    packet = manifest["source_coverage"]["inventory_audit_repair"]["clarification_context"]
    decision = provider.expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload), manifest=manifest)
    verified = verify_manifest(manifest, decision)
    for prompt in (provider._build_prompt(manifest), provider._build_verification_prompt(verified)):
        assert "Earlier context." in prompt and "Was the earlier request permanent?" in prompt
        assert "Do not extract any new-source point" in prompt
        assert "complete-authored-user-v1" in prompt
    assert manifest["source_coverage"]["inventory_input"] == source
    assert "later_user_contexts" not in source and packet["selection"]["source_ref"]["source_id"] != source["source_id"]


@pytest.mark.parametrize("fault", ["content_hash", "reply_hash", "target", "source_identity", "not_pending"])
def test_resealed_runtime_context_tampering_is_rejected(fault):
    manifest, _payload = transport()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    packet = repair["clarification_context"]
    if fault == "content_hash":
        packet["content"] += " "
    elif fault == "reply_hash":
        packet["selection"]["reply"]["sha256"] = "0" * 64
    elif fault == "target":
        packet["selection"]["target"]["sha256"] = "0" * 64
    elif fault == "source_identity":
        packet["selection"]["source_ref"]["source_id"] = "another-source"
    else:
        packet["selection"]["target"]["w"] = 1
    reseal(repair)
    with pytest.raises(ValueError, match="clarification_changed"):
        provider._build_prompt(manifest)


@pytest.mark.parametrize("audit_only", [None, False])
def test_explicit_parser_rejects_clarification_outside_audit(clarification, audit_only):
    from harness_mem.commands.dream import _freeze_explicit_repair_scope
    data = clarification
    source = {"origin_run_id": data["origin"].id, "predecessor_ids": [data["key"]],
              "clarification_context": data["selection"]}
    if audit_only is not None:
        source["audit_only"] = audit_only
    with pytest.raises(ValueError, match="dream_repair_source_invalid"):
        run(_freeze_explicit_repair_scope(data["backend"], project_name="demo", project_root=data["root"],
            run_id="residual-run", scope={"groups": [], "source": source}))


def test_explicit_parser_passes_exact_selection_to_existing_audit_owner(clarification):
    from harness_mem.commands.dream import _freeze_explicit_repair_scope
    data = clarification
    frozen = run(_freeze_explicit_repair_scope(data["backend"], project_name="demo", project_root=data["root"],
        run_id="residual-run", scope={"groups": [], "source": {"audit_only": True,
            "origin_run_id": data["origin"].id, "predecessor_ids": [data["key"]],
            "clarification_context": data["selection"]}}))
    assert frozen["source"]["clarification_context"] == data["selection"]


def test_clarification_cannot_supply_external_r_or_new_source_coordinates():
    manifest, payload = transport()
    packet = manifest["source_coverage"]["inventory_audit_repair"]["clarification_context"]
    span = payload["patches"][0]["spans"][0]
    span.update(d="superseded", p=[], c=[], r=[{"context_sha256": packet["context_sha256"],
        "exchange_index": 2, "message_index": 0, "content_sha256": packet["selection"]["reply"]["sha256"],
        "s": 0, "e": 1}])
    with pytest.raises(ValueError):
        provider.expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload), manifest=manifest)


def test_absent_optional_context_preserves_existing_prompt_shape():
    manifest, payload = transport_residual()
    decision = provider.expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload), manifest=manifest)
    verified = verify_manifest(manifest, decision)
    assert "Optional inventory_audit_repair.clarification_context" not in provider._build_prompt(manifest)
    assert "Optional inventory_audit_repair.clarification_context" not in provider._build_verification_prompt(verified)


def clarified_child(data, *, split=False):
    """A failed child has a positive temporary vote whose clarification remains required."""
    child, _frozen, state = audit_child(data)
    frozen = prepare(data)
    audit = state["inventory_verification"]
    target = data["selection"]["target"]
    spans = [{"s": target["s"], "e": target["e"], "d": "temporary", "p": [], "c": [], "r": []}]
    if split:
        middle = (target["s"] + target["e"]) // 2
        spans = [{**spans[0], "e": middle}, {**spans[0], "s": middle}]
    audit["windows"][target["w"]]["spans"] = spans
    audit["audit"] = [row for row in audit["audit"] if row["w"] != target["w"]] + [
        {"w": target["w"], "span_index": index, "verdict": "supported"} for index in range(len(spans))]
    seal_audit(audit)
    continuation = child.continuation
    continuation["explicit_repair_scope"]["source"] = frozen
    continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(frozen)
    run(data["backend"].structured_store.save_dream_run(child))
    return child, frozen, state


def prepare_grandchild(data, child, **kwargs):
    return run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="clarified-grandchild", origin_run_id=child.id,
        predecessor_ids=[data["key"]], **kwargs))


@pytest.mark.parametrize("split", [False, True])
def test_grandchild_omitted_selection_retains_positive_source_dependency(clarification, monkeypatch, split):
    data = clarification
    child, frozen, _state = clarified_child(data, split=split)
    before = data["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id)
    manifest = prepare_grandchild(data, child)
    prepared, _item, _rows = run(owner._prepared(data["backend"], origin=child, frozen=frozen,
        key=data["key"], project_name="demo", project_root=data["root"], run_id="clarified-grandchild"))
    repair = prepared["inventory_audit_repair"]
    assert manifest["clarification_context"] == frozen["clarification_context"] == data["selection"]
    assert repair["clarification_context"]["selection"] == data["selection"]
    assert repair["clarification_context"]["content"] == rebuilt(data)["inventory_audit_repair"]["clarification_context"]["content"]
    assert data["selection"]["target"]["w"] not in {row["w"] for row in repair["pending_spans"]}
    retained = [row for row in repair["retained_spans"] if row["w"] == data["selection"]["target"]["w"]]
    assert len(retained) == (2 if split else 1) and all(row["span"]["d"] == "temporary" for row in retained)
    assert manifest["source_bindings"][data["key"]]["residual_sha256"] == owner._digest(repair)
    assert data["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id) == before
    seen = []
    def before_native(_provider, **kwargs):
        native = kwargs["manifest"]
        basis = provider._residual_inventory_basis(native)
        packet = native["source_coverage"]["inventory_audit_repair"]["clarification_context"]
        assert packet["selection"] == data["selection"]
        assert all(w != data["selection"]["target"]["w"] for w, _index in basis["pending"])
        assert "Only test it then" in provider._build_prompt(native)
        seen.append(native)
        raise ValueError("fixture_stop_before_native")
    monkeypatch.setattr("harness_mem.autonomous.worker._decide_with_candidate_retry", before_native)
    async def persist():
        pass
    result = run(owner.run_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
        run_id="clarified-grandchild", manifest=manifest, checkpoint={}, notes=[],
        provider=data["provider"], persist=persist))
    assert result["status"] == "unresolved" and len(seen) == 1 and data["provider"].calls == []


@pytest.mark.parametrize("fault", ["source_ref", "reply", "target", "range"])
def test_inherited_selection_cannot_be_replaced_or_expanded(clarification, fault):
    data = clarification
    child, _frozen, _state = clarified_child(data)
    changed = deepcopy(data["selection"])
    if fault == "source_ref":
        changed["source_ref"]["source_id"] = "another-source"
    elif fault == "reply":
        changed["reply"]["sha256"] = "e" * 64
    elif fault == "target":
        changed["target"]["w"] = 0
    else:
        changed["target"]["e"] += 1
    with pytest.raises(ValueError, match="clarification_selection_conflict"):
        prepare_grandchild(data, child, clarification_context=changed)
    assert data["provider"].calls == []


@pytest.mark.parametrize("fault", ["raw_missing", "raw_changed", "metadata_missing", "rendering_metadata",
                                   "native_proof_missing", "native_proof_changed"])
def test_inherited_dependency_reopens_complete_raw_metadata_and_native_proof(clarification, monkeypatch, fault):
    data = clarification
    child, _frozen, _state = clarified_child(data, split=True)
    ledger = data["backend"].transcript_store
    identity = data["selection"]["source_ref"]["source_id"]
    if fault.startswith("raw_"):
        reconstruct = ledger.reconstruct_raw
        def altered_raw(source_id, *args, **kwargs):
            if source_id == identity:
                if fault == "raw_missing":
                    raise ValueError("fixture_missing_immutable_raw")
                return reconstruct(source_id, *args, **kwargs) + b"changed"
            return reconstruct(source_id, *args, **kwargs)
        monkeypatch.setattr(ledger, "reconstruct_raw", altered_raw)
    else:
        get_revision = ledger.get_revision
        def altered_revision(source_id, *args, **kwargs):
            revision = get_revision(source_id, *args, **kwargs)
            if source_id != identity or revision is None:
                return revision
            metadata = dict(revision.metadata)
            if fault == "metadata_missing":
                metadata = {}
            elif fault == "rendering_metadata":
                metadata["authored_rendering_sha256"] = "e" * 64
            elif fault == "native_proof_missing":
                metadata.pop("authored_source_report_native_sha256", None)
            else:
                metadata["native_input_sha256"] = "e" * 64
            return revision.model_copy(update={"metadata": metadata})
        monkeypatch.setattr(ledger, "get_revision", altered_revision)
    with pytest.raises(ValueError):
        prepare_grandchild(data, child)
    assert data["provider"].calls == []


def test_inherited_guard_reopens_dependency_after_prepare(clarification, monkeypatch):
    data = clarification
    child, _frozen, _state = clarified_child(data)
    manifest = prepare_grandchild(data, child)
    reopen = original._reopen_complete_user_context
    identity = data["selection"]["source_ref"]["source_id"]
    def unavailable(backend, source):
        if identity in source.locator:
            return "unverified", "fixture_lost_role_proof", None, False, source
        return reopen(backend, source)
    monkeypatch.setattr(original, "_reopen_complete_user_context", unavailable)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt",
                        lambda *_args, **_kwargs: pytest.fail("worker must not start"))
    async def persist():
        pass
    checkpoint = {}
    result = run(owner.run_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
        run_id="clarified-grandchild", manifest=manifest, checkpoint=checkpoint, notes=[],
        provider=data["provider"], persist=persist))
    assert result["status"] == "unresolved" and data["provider"].calls == []
    state = checkpoint["source_inventory_audit"]["source_coverage"][data["key"]]
    assert state["reason_code"] == "source_coverage_audit_clarification_user_unproved"
