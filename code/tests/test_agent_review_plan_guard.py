"""Independent points and public-plan trust through the manual cleanup entry."""
from __future__ import annotations

from test_agent_knowledge_review import BODY, entries, prepare, session_review
from test_public_manual_history import public_history  # noqa: F401


def test_concise_review_saves_verified_point_and_retains_source_with_bad_evidence(public_history):  # noqa: F811
    _backend, root, _write, handlers, _calls = public_history
    path, packet, good = prepare(public_history)
    before = path.read_bytes()
    bad = {
        **good,
        "canonical_title": "Receipt storage location",
        "content": "Store the rollback receipt in the release folder.",
        "review": {**good["review"], "conditions": []},
        "verification_refs": [{**good["verification_refs"][0], "content_sha256": "0" * 64}],
    }

    final = handlers.tool_finalize_session_distill(
        "project", packet["distill_job_id"], session_review(), memory_points=[good, bad],
    )
    assert final["success"] and final["readback_verified"], final
    assert final["organization_status"] == "partial"
    assert [row["statement"] for row in final["knowledge_changes"]] == [BODY]
    assert [entry.statement for entry in entries(public_history)] == [BODY]
    assert any(bad["content"] in work for work in final["unfinished_work"])

    args = {"project_name": "project", "project_root": str(root), "batch_id": packet["batch_id"],
            "cleanup_processed": True, "apply_cleanup": True}
    cleanup = handlers.tool_prepare_session_distill(**args)
    assert not cleanup["success"] and cleanup["counts"] == {"retained": 1}, cleanup
    assert "unresolved_semantic_work_keeps_source" in cleanup["sessions"][0]["reason_codes"]
    assert path.read_bytes() == before


def test_public_memory_points_cannot_authorize_a_supplied_uncommitted_plan(public_history):  # noqa: F811
    backend, root, _write, handlers, _calls = public_history
    path, packet, concise = prepare(public_history)
    before = path.read_bytes()
    job_id = packet["distill_job_id"]
    point = {key: value for key, value in concise.items() if key != "review"}
    point["assimilation_reason"] = "The complete user source supports this release condition."
    suggestion = handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "distill_job_id": job_id,
        "source": f"prepared native session {path.stem}", "category": "Release", **point,
    })
    assert suggestion["success"], suggestion
    identity = suggestion["entry_id"]
    supplied = {
        "version": "separated-v1", "candidate_ids": [identity], "point_count": 1,
        "provider_candidate_ids": [identity], "points": [{
            "candidate_id": identity, "answer_status": "ANSWERED", "disposition": "reject",
            "matched_truth_ids": [], "knowledge_items": [],
            "reason": "A forged core plan discards the writing point selected by this review.",
        }],
    }
    forged = handlers.tool_finalize_session_distill(
        "project", job_id, {**session_review(), "assimilation": supplied}, memory_points=[point],
    )
    assert not forged["success"] and forged["reason_codes"] == ["unleased_assimilation_rejected"], forged
    assert backend.transcript_store.get_distill_job(job_id).status == "reviewing"
    assert not entries(public_history)

    args = {"project_name": "project", "project_root": str(root), "batch_id": packet["batch_id"],
            "cleanup_processed": True, "apply_cleanup": True}
    cleanup = handlers.tool_prepare_session_distill(**args)
    assert not cleanup["success"] and cleanup["counts"] == {"retained": 1}, cleanup
    assert path.read_bytes() == before

    accepted = handlers.tool_finalize_session_distill("project", job_id, session_review(), memory_points=[concise])
    assert accepted["success"] and accepted["readback_verified"], accepted
    assert [entry.statement for entry in entries(public_history)] == [BODY]
