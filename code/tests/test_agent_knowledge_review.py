"""The concise Agent review uses the public write and cleanup owners, in isolation."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import time

import pytest

from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.adapters.projection_repair import load_source_observation_projection
from test_public_manual_history import public_history  # noqa: F401


BODY = "Publish only after security approval; retain the rollback receipt."
TITLE = "Release approval and rollback evidence"


def review(**changes):
    return {"support": "supported", "use": "standing_decision",
            "reason": "The complete user source explicitly requires these future release conditions.",
            "conditions": ["only after security approval", "retain the rollback receipt"],
            "undecided_state": None, **changes}


def session_review():
    return {"session_summary": "The user sets release approval and rollback evidence requirements.",
            "final_user_request": "Retain the stated release requirements.",
            "final_outcome": "The release conditions were stated; no release was performed.",
            "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
            "evidence_status": "answered", "promotion_decision": "promote"}


def prepare(fixture, name="release", body=BODY):
    backend, root, write, handlers, _calls = fixture
    path = write(name, body)
    os.utime(path, (time.time() - 120, time.time() - 120))
    inventory = handlers["inspect_sessions"](project_root=str(root), clients=["cursor"])
    selected = [row for row in inventory["sessions"] if row["session_id"] == name]
    packet = handlers["prepare_session_distill"](project_name="project", project_root=str(root), batch_sessions=selected)
    assert packet["success"], packet
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    source = load_source_observation_projection(backend, source_id=job.source_id, source_revision=job.source_revision)
    window = render_distill_exchange_windows(source.raw_content, [1])[0]
    point = {"content": body, "canonical_title": TITLE, "topic_path": ["Release"],
             "evidence_basis": "user_statement", "verification_outcome": "verified",
             "verification_refs": [{"kind": "user_statement", "exchange_index": 1,
                                    "content_sha256": window["content_sha256"], "role": "user"}],
             "assimilation_disposition": "add", "review": review()}
    return path, packet, point


def finalize(fixture, packet, point, **kwargs):
    return fixture[3]["finalize_session_distill"](
        "project", packet["distill_job_id"], session_review(), memory_points=[point], **kwargs)


def entries(fixture):
    return asyncio.run(fixture[0].structured_store.knowledge_store.list_entries("project"))


def test_checked_external_rule_survives_reopen_and_flags_a_condition_the_agent_omitted(
    public_history, tmp_path, monkeypatch,  # noqa: F811
):
    from harness_mem.commands.evidence_admission import resolve_repository_evidence_path, validate_knowledge_sources
    from harness_mem.config import merge

    backend, root, _, _, _ = public_history
    config = tmp_path / "user-config.toml"
    monkeypatch.setattr(merge, "_user_config_path", lambda: config)
    monkeypatch.setattr(merge, "_legacy_user_config_path", lambda: tmp_path / "absent.json")
    shared = tmp_path / "shared-reference"
    shared.mkdir()
    policy = shared / "release.md"
    full = "Publish the release only after security approval and keep the rollback receipt."
    policy.write_text(full, encoding="utf-8")
    config_text = f'[evidence]\nrepository_roots = ["{shared.as_posix()}"]\n'
    (root / ".harness-mem.toml").write_text(config_text, encoding="utf-8")
    assert merge.load_merged_config(root).evidence_repository_roots == ()
    assert resolve_repository_evidence_path(policy.as_posix(), root)[0] is None
    config.write_text(config_text, encoding="utf-8")
    assert resolve_repository_evidence_path(os.path.relpath(policy, root), root)[0] is None

    _, packet, point = prepare(public_history, body="Please verify the release workflow against the current policy.")
    point.update(content="Publish the release and keep the rollback receipt.", evidence_basis="repository",
                 review=review(use="reusable_knowledge", conditions=[]), verification_refs=[{
                     "kind": "repository", "locator": policy.as_posix(),
                     "content_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
                 }])
    blocked = finalize(public_history, packet, point)
    assert blocked["error"] == "source_conditions_need_review", blocked
    assert [row["condition"] for row in blocked["condition_checks"]] == [full]
    assert not entries(public_history)

    condition = "only after security approval"
    point["verification_refs"].append(dict(point["verification_refs"][0]))
    point.update(content=full, review=review(
        use="reusable_knowledge", conditions=[condition],
        evidence=[{"ref": 1, "target": "claim", "quote": full},
                  {"ref": 2, "target": "condition", "condition": condition, "quote": condition}],
    ))
    saved = finalize(public_history, packet, point)
    assert saved["success"] and saved["readback_verified"], saved
    entry, = entries(public_history)
    assert entry.statement == full and entry.source_report is None
    store = backend.structured_store.knowledge_store
    sources = asyncio.run(store.list_sources(entry.id))
    assert [(source.source_kind, source.locator) for source in sources] == [("repository", policy.as_uri())]
    assert [binding.target for binding in sources[0].bindings] == ["claim", "condition"]

    def reopen():
        return asyncio.run(validate_knowledge_sources(backend, project_name="project", sources=sources, project_root=root))

    assert reopen().verification_outcome == "verified"
    policy.write_text("The release workflow changed.", encoding="utf-8")
    assert reopen().verification_outcome == "contradicted"
    config.write_text("", encoding="utf-8")
    assert reopen().verification_outcome == "unverified"


def test_concise_review_writes_reopens_and_cleans_only_completed_source(public_history):  # noqa: F811
    backend, root, write, handlers, calls = public_history
    other = write("unprocessed", "A different conversation remains unread.")
    untouched = other.read_bytes()
    path, packet, point = prepare(public_history)
    before = path.read_bytes()
    result = finalize(public_history, packet, point)
    assert result["success"] and result["readback_verified"], result
    assert [entry.statement for entry in entries(public_history)] == [BODY]
    assert not calls
    replay = finalize(public_history, packet, point)
    assert replay["success"] and len(entries(public_history)) == 1, replay
    note = result.get("note_path")
    arguments = {"project_name": "project", "project_root": str(root),
                 "batch_id": packet["batch_id"], "cleanup_processed": True}
    preview = handlers["prepare_session_distill"](**arguments)
    assert preview["success"] and preview["counts"] == {"ready": 1}, preview
    assert path.read_bytes() == before
    cleaned = handlers["prepare_session_distill"](**arguments, apply_cleanup=True)
    assert cleaned["success"] and cleaned["counts"] == {"deleted": 1}, cleaned
    assert not path.exists() and other.read_bytes() == untouched
    saved = entries(public_history)[0].to_dict()
    asyncio.run(backend.close())
    asyncio.run(backend.init())
    assert entries(public_history)[0].to_dict() == saved
    search = handlers["search_memory"](query=TITLE, project_name="project", scope="project")
    assert BODY in str(search), search
    assert handlers["prepare_session_distill"](**arguments, apply_cleanup=True)["counts"] == {"already_deleted": 1}
    if note:
        from pathlib import Path
        assert Path(note).is_file()


@pytest.mark.parametrize("damage", ["partial", "temporary", "missing_condition", "wrong_digest", "wrong_author", "changed_source", "missing_review", "mixed_contract"])
def test_bad_judgments_cannot_write_and_changed_native_sources_cannot_be_cleaned(public_history, damage):  # noqa: F811
    _backend, root, _write, handlers, _calls = public_history
    path, packet, point = prepare(public_history)
    if damage == "partial":
        point["review"]["support"] = "partial"
    elif damage == "temporary":
        point["review"]["use"] = "task_context"
    elif damage == "missing_condition":
        point["content"] = "Publish only after security approval."
    elif damage == "wrong_digest":
        point["verification_refs"][0]["content_sha256"] = "0" * 64
    elif damage == "wrong_author":
        point["verification_refs"][0]["role"] = "assistant"
    elif damage == "changed_source":
        path.write_bytes(path.read_bytes() + b"\nchanged after selection")
    elif damage == "missing_review":
        point.pop("review")
        point["assimilation_reason"] = "A rationale alone is not a complete content judgment."
    result = finalize(public_history, packet, point,
                      **({"final_scope_judgment": {"points": []}} if damage == "mixed_contract" else {}))
    if damage == "changed_source":
        # The immutable selected revision remains valid evidence; a later
        # native append must nevertheless prevent deleting that changed file.
        assert [entry.statement for entry in entries(public_history)] == [BODY]
    else:
        assert not result["success"] or not result["knowledge_changes"], result
        assert not entries(public_history)
    before = path.read_bytes()
    cleanup = handlers["prepare_session_distill"](project_name="project", project_root=str(root),
        batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not cleanup["success"] and path.read_bytes() == before, cleanup


def test_replacement_requires_preservation_and_exact_current_target(public_history):  # noqa: F811
    _path, packet, point = prepare(public_history)
    assert finalize(public_history, packet, point)["success"]
    old = entries(public_history)[0]
    new = BODY + " Use the signed release artifact."
    path, next_packet, next_point = prepare(public_history, "release-update", new)
    next_point["assimilation_disposition"] = "replace"
    next_point["target_knowledge"] = [{"title": old.title, "statement": old.statement, "project_name": old.project_name}]
    before = old.to_dict()
    rejected = finalize(public_history, next_packet, next_point)
    assert not rejected["success"] and entries(public_history)[0].to_dict() == before, rejected
    next_point["review"]["preserves_meaning"] = True
    stale = copy.deepcopy(next_point)
    stale["target_knowledge"][0]["statement"] += " old version"
    rejected = finalize(public_history, next_packet, stale)
    assert not rejected["success"] and entries(public_history)[0].to_dict() == before, rejected
    accepted = finalize(public_history, next_packet, next_point)
    assert accepted["success"] and accepted["readback_verified"], accepted
    assert [entry.statement for entry in entries(public_history)] == [new]
    assert path.exists()


def test_confirm_reviews_existing_conditions_without_new_knowledge(public_history):  # noqa: F811
    _path, packet, point = prepare(public_history)
    assert finalize(public_history, packet, point)["success"]
    old = entries(public_history)[0]
    _path, again, confirmation = prepare(public_history, "release-confirm")
    confirmation["assimilation_disposition"] = "confirm"
    confirmation["target_knowledge"] = [{"title": old.title, "statement": old.statement, "project_name": old.project_name}]
    result = finalize(public_history, again, confirmation)
    assert result["success"], result
    assert [entry.id for entry in entries(public_history)] == [old.id]
