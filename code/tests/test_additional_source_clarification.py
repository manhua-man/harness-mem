"""Explicit appended context stays bound to exact pending source ranges."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from test_source_audit_clarification import (
    captured as captured, coverage as coverage, terminal as terminal, residual as residual,
    clarification as clarification, clarified_child, prepare_grandchild, rebuilt, reseal, sha,
    transport, verify_manifest, run, seal_audit,
)
from harness_mem.adapters.snapshot import _native_codex_authored_texts, persist_session_snapshot
from harness_mem.autonomous import provider
from harness_mem.autonomous.models import NativeResidualSourceCoverageExtractionDecision
from harness_mem.commands import dream_source_audit as owner
from harness_mem.commands.session_inventory import session_reference
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.observation import Observation


@pytest.fixture
def bundle(clarification):
    data = clarification
    child, frozen, state = clarified_child(data)
    window = data["prepared"]["authored_user_exchanges"][0]
    end = len(window["text"])
    bounds = [0, end // 3, 2 * end // 3, end]
    audit = state["inventory_verification"]
    audit["windows"][0]["spans"] = [dict(s=start, e=stop, d="unclear", p=[], c=[], r=[])
        for start, stop in zip(bounds, bounds[1:])]
    audit["audit"] = [v for v in audit["audit"] if v["w"] != 0] + [
        dict(w=0, span_index=i, verdict="unclear") for i in range(3)]
    seal_audit(audit)
    run(data["backend"].structured_store.save_dream_run(child))
    job = data["prepared"]["job"]
    reply = json.dumps({"question": "Were these three old acceptance conditions lasting?",
                        "answer": "All three were only for that acceptance."})
    records = [{"type": "session_meta", "payload": {"id": job.session_id, "cwd": str(data["root"])}}]
    for index, (role, text) in enumerate((("user", "Original user context."),
            ("assistant", "Question about the three exact old ranges."), ("user", reply))):
        records.append({"type": "response_item", "payload": {"type": "message", "turn_id": str(index),
            "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}})
    native = ("\n".join(json.dumps(row) for row in records) + "\n").encode()
    rendering = _native_codex_authored_texts(native)[0]
    snapshot = run(persist_session_snapshot(data["backend"], Observation(session_id=job.session_id,
        client=job.client, raw_content=rendering, content_type="transcript", timestamp=datetime.now(timezone.utc),
        metadata={}), project_name="demo", project_root=str(data["root"]), client=job.client,
        session_id=job.session_id, source_kind="jsonl", source_uri=(data["root"] / "clarification.jsonl").as_uri(),
        source_text=rendering, raw_bytes=rendering.encode(), native_input_bytes=native,
        parser_version="codex-conversation-v3", capture_config=MergedConfig()))
    selections = [deepcopy(data["selection"])]
    for index, (start, stop) in enumerate(zip(bounds, bounds[1:])):
        selected = deepcopy(data["selection"])
        selected["source_ref"] = session_reference(job.client, job.session_id, snapshot.source.id, snapshot.source.source_revision)
        selected["reply"]["sha256"] = sha(reply)
        selected["target"].update(w=0, span_index=index, s=start, e=stop, sha256=window["sha256"])
        selections.append(selected)
    return data, child, frozen, {"selections": selections}


def test_append_three_new_pending_contexts_preserves_old_revision_and_dependency(bundle):
    data, child, frozen, selection = bundle
    legacy = rebuilt(data)["inventory_audit_repair"]["clarification_context"]
    manifest = prepare_grandchild(data, child, clarification_context=selection)
    prepared, _, _ = run(owner._prepared(data["backend"], origin=child, frozen=frozen, key=data["key"],
        project_name="demo", project_root=data["root"], run_id="clarified-grandchild", clarification_context=selection))
    contexts = prepared["inventory_audit_repair"]["clarification_context"]["contexts"]
    assert len(contexts) == 4 and contexts[0] == legacy
    assert contexts[0]["selection"]["source_ref"]["source_revision"] != contexts[1]["selection"]["source_ref"]["source_revision"]
    assert manifest["clarification_context"] == selection
    assert owner._clarification_selection(manifest, None) == selection
    assert owner._clarification_selection(manifest, deepcopy(selection)) == selection
    assert {v["selection"]["target"]["span_index"] for v in contexts[1:]} == {0, 1, 2}
    assert all(v["selection"]["target"]["w"] == 0 for v in contexts[1:])
    assert data["provider"].calls == []


def test_append_uses_original_frozen_prefix_representation(bundle):
    _data, _child, frozen, selection = bundle
    supplied = deepcopy(selection)
    supplied["selections"][0] = dict(reversed(list(supplied["selections"][0].items())))
    result = owner._clarification_selection(frozen, supplied)
    assert json.dumps(result["selections"][0]) == json.dumps(frozen["clarification_context"])


def test_inherited_bundle_reopens_every_revision_after_all_targets_are_retained(bundle):
    data, child, frozen, selection = bundle
    inherited = {**frozen, "clarification_context": deepcopy(selection)}
    first = run(owner._prepared(data["backend"], origin=child, frozen=inherited, key=data["key"],
        project_name="demo", project_root=data["root"], run_id="clarified-grandchild"))[0]
    state = next(iter(child.continuation["source_inventory_audit"]["source_coverage"].values()))
    audit = state["inventory_verification"]
    for span in audit["windows"][0]["spans"]:
        span["d"] = "temporary"
    for vote in audit["audit"]:
        if vote["w"] == 0:
            vote["verdict"] = "supported"
    seal_audit(audit)
    run(data["backend"].structured_store.save_dream_run(child))
    prepared = run(owner._prepared(data["backend"], origin=child, frozen=inherited, key=data["key"],
        project_name="demo", project_root=data["root"], run_id="clarified-grandchild"))[0]
    assert prepared["inventory_audit_repair"]["clarification_context"] == first["inventory_audit_repair"]["clarification_context"]
    assert not any(span["w"] in {0, 1} for span in prepared["inventory_audit_repair"]["pending_spans"])
    assert inherited["clarification_context"] == selection


def test_new_revision_still_requires_native_authored_user_proof(bundle, monkeypatch):
    from harness_mem.commands import evidence_admission
    data, child, _frozen, selection = bundle
    revision_id = selection["selections"][1]["source_ref"]["source_revision"]
    original = evidence_admission._source_report_author_indexes
    def deny_new(revision, *args):
        return set() if revision.source_revision == revision_id else original(revision, *args)
    monkeypatch.setattr(evidence_admission, "_source_report_author_indexes", deny_new)
    with pytest.raises(ValueError, match="clarification_native_user_unproved"):
        prepare_grandchild(data, child, clarification_context=selection)
    assert data["provider"].calls == []


def test_bundle_guard_reopens_new_packet_before_worker(bundle, monkeypatch):
    data, child, _frozen, selection = bundle
    manifest = prepare_grandchild(data, child, clarification_context=selection)
    reopen = owner._clarification_context
    def changed(*args, **kwargs):
        packet = reopen(*args, **kwargs)
        if packet["selection"]["target"]["w"] == 0:
            packet["raw_sha256"] = "a" * 64
        return packet
    monkeypatch.setattr(owner, "_clarification_context", changed)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt",
                        lambda *_args, **_kwargs: pytest.fail("worker must not start"))
    async def persist():
        pass
    result = run(owner.run_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
        run_id=manifest["run_id"], manifest=manifest, checkpoint={}, notes=[], provider=data["provider"], persist=persist))
    assert result["status"] == "unresolved" and data["provider"].calls == []


@pytest.mark.parametrize("fault", ["remove", "replace", "reorder"])
def test_inherited_multi_selection_prefix_cannot_change(bundle, fault):
    _data, _child, frozen, selection = bundle
    inherited = {**frozen, "clarification_context": selection}
    changed = deepcopy(selection)
    if fault == "remove":
        changed["selections"].pop()
    elif fault == "replace":
        changed["selections"][1]["reply"]["sha256"] = "b" * 64
    else:
        changed["selections"][1], changed["selections"][2] = changed["selections"][2], changed["selections"][1]
    with pytest.raises(ValueError, match="clarification_selection_conflict"):
        owner._clarification_selection(inherited, changed)


@pytest.mark.parametrize("fault", ["remove", "replace", "reorder", "duplicate", "overlap",
                                   "retained", "reply_hash", "source_ref", "new_not_exact"])
def test_bundle_prefix_and_new_source_targets_are_strict(bundle, fault):
    data, child, frozen, selection = bundle
    changed = deepcopy(selection)
    rows = changed["selections"]
    if fault == "remove":
        rows.pop(0)
    elif fault == "replace":
        rows[0]["reply"]["sha256"] = "a" * 64
    elif fault == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    elif fault == "duplicate":
        rows.append(deepcopy(rows[1]))
    elif fault == "overlap":
        rows[2]["target"]["s"] -= 1
    elif fault == "retained":
        retained = data["prepared"]["authored_user_exchanges"][2]
        rows[1]["target"].update(w=2, span_index=0, s=0, e=len(retained["text"]), sha256=retained["sha256"])
    elif fault == "reply_hash":
        rows[1]["reply"]["sha256"] = "b" * 64
    elif fault == "source_ref":
        rows[1]["source_ref"]["reference_id"] = "b" * 64
    else:
        rows[3]["target"]["e"] -= 1
    with pytest.raises(ValueError):
        prepare_grandchild(data, child, clarification_context=changed)
    assert data["provider"].calls == []


@pytest.mark.parametrize("fault", [None, "content", "reply", "target", "duplicate", "nested"])
def test_both_transport_prompts_validate_each_packet_in_order(fault):
    manifest, payload = transport()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    original = deepcopy(repair["clarification_context"])
    extra = deepcopy(original)
    # A second nonoverlapping exact range in the same original window.
    target = original["selection"]["target"]
    middle = (target["s"] + target["e"]) // 2
    original["selection"]["target"]["e"] = middle
    extra["selection"]["target"].update(s=middle, span_index=target["span_index"] + 1)
    repair["clarification_context"] = {"contexts": [original, extra]}
    reseal(repair)
    decision = provider.expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload), manifest=manifest)
    if fault == "content":
        extra["content"] += " "
    elif fault == "reply":
        extra["selection"]["reply"]["sha256"] = "b" * 64
    elif fault == "target":
        extra["selection"]["target"]["sha256"] = "b" * 64
    elif fault == "duplicate":
        repair["clarification_context"]["contexts"][1] = deepcopy(original)
    elif fault == "nested":
        repair["clarification_context"]["contexts"][1] = {"contexts": [extra]}
    reseal(repair)
    if fault:
        for call in (lambda: provider._build_prompt(manifest),
                     lambda: provider._build_verification_prompt(verify_manifest(manifest, decision))):
            with pytest.raises(ValueError, match="clarification_changed"):
                call()
        return
    for prompt in (provider._build_prompt(manifest), provider._build_verification_prompt(verify_manifest(manifest, decision))):
        assert "ordered contexts bundle" in prompt and "ONLY to its own selection.target" in prompt
        assert "no extraction, current-truth" in prompt
