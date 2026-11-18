"""One-output attributed refinement through the real canonical fixture store."""
from harness_mem.autonomous.models import CandidateVerificationDecision, CandidateVerificationPoint, UpdateMeaningJudgment, DREAM_SOURCE_RECHECK_CONTRACT
from harness_mem.commands.knowledge_assimilation import commit_shared_knowledge_change, record_assimilation_result
from harness_mem.commands.separated_assimilation import target_version, final_scope_verification_rows, judged_update_payload
from harness_mem.core.schemas.knowledge import KnowledgeCandidate
from harness_mem.core.schemas.source_report import (
    ReportOmission, bind_report_preservation_inventory, report_output_scope_text, source_report_snapshot,
)
from test_shared_maintenance_proposals import _original_report_classification
from harness_mem.read_knowledge import search_current_knowledge

# Reuse the immutable native-source fixture setup; this creates only tmp_path data.
from test_dream_stage4_contract import backend as backend
from test_dream_stage4_contract import _capture_report, _output, _run


def _verdict(report, meaning=None):
    return CandidateVerificationDecision(points=[CandidateVerificationPoint(
        candidate_index=0, semantic_support="supported", future_scope="durable", source_use="reusable_knowledge",
        reason="The rendered report and source authority are supported by this fixture.",
        scope_segments=[{"text": report_output_scope_text(report), "source_use": "reusable_knowledge",
                         "future_scope": "durable", "source_support": "supported", "content_role": "claim", "standalone": True}],
        update_meaning_judgment=meaning,
    )]).model_dump(mode="json")


def _independent_report_final(point, *, candidate_id, old, written, omissions):
    """Supply a fresh indexed final vote over the exact old/new fixture endpoints."""
    from test_report_original_inventory import native_vote, expand

    target = {"id": old.id, "title": old.title, "statement": old.statement,
        "topic_path": list(old.module_path), "source_report": source_report_snapshot(old.source_report)}
    target["version"] = target_version(target)
    item = {**point["knowledge_items"][0], "title": written.render_title(),
        "statement": written.render_statement(), "source_report": source_report_snapshot(written)}
    inventory = bind_report_preservation_inventory(owner=candidate_id, target=target, items=[item],
        omissions=[omission.model_dump(mode="json") for omission in omissions],
        classification=_original_report_classification(old.source_report, omissions).model_dump(mode="json"),
        mode="literal_projection" if point.get("report_split") else "full_revision")
    payload = {"candidate_id": candidate_id, "disposition": point["disposition"], "targets": [target],
        "knowledge_items": [item], "report_preservation_inventory": inventory}
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": final_scope_verification_rows(
        payload, [{"kind": "source_report", "role": "assistant", "content": report.render_statement()}
                  for report in (old.source_report, written)])}
    final = expand(manifest, native_vote(manifest))
    stamped, blocked = judged_update_payload(payload, final, manifest["candidates"])
    assert blocked is None
    for key in ("report_preservation_inventory", "update_meaning_judgment", "retained_conditions", "undecided_state"):
        if key in stamped:
            point[key] = stamped[key]
    point["final_scope_judgment"] = final.model_dump(mode="json")
    return point


def test_one_retained_report_replaces_original_and_reads_back(backend, tmp_path):
    report, ref = _capture_report(backend, "Alpha cache stays local. Ran one check.")
    root = tmp_path / "project"
    root.mkdir()
    old_ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="single-report-before", project_name="demo", candidate_type="memory",
                                     statement=report.text, source_report=report),
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(), "statement": report.render_statement(),
            "topic_path": ["reports"], "claim_kind": "source_report"}], "reason": "Retain the original attributed account.",
            "final_scope_judgment": _verdict(report)}, project_root=root, source_refs=[ref]))
    store = backend.structured_store.knowledge_store
    old = _run(store.get_entry(old_ids[0], project_name="demo"))
    proposal, retained = _output(report, "Alpha cache", "Alpha cache stays local.")
    version = target_version({"title": old.title, "statement": old.statement,
                              "topic_path": list(old.module_path), "source_report": source_report_snapshot(old.source_report)})
    meaning = UpdateMeaningJudgment(relationship="preserves_applicable_meaning", predecessor_conditions=[],
        predecessor_statements=[old.statement], predecessor_versions=[version], successor_statements=[retained.render_statement()],
        basis="Keep the complete scoped account while omitting a particular-run receipt.")
    point = {"disposition": "refine", "matched_truth_ids": old_ids,
        "knowledge_items": [{"title": retained.render_title(), "statement": retained.render_statement(),
                             "topic_path": ["reports"], "claim_kind": "source_report"}],
        "reason": "Retain the scoped cache account and remove one temporary receipt.",
        "report_split": {"original_support": "supported", "outputs": [proposal.model_dump(mode="json")],
                         "omissions": [ReportOmission(text=" Ran one check.", classification="temporary_context").model_dump(mode="json")]},
        "update_meaning_judgment": meaning.model_dump(mode="json"), "final_scope_judgment": _verdict(retained, meaning)}
    _independent_report_final(point, candidate_id="single-report-refinement", old=old, written=retained,
        omissions=[ReportOmission(text=" Ran one check.", classification="temporary_context")])
    committed = _run(commit_shared_knowledge_change(backend,
        candidate=KnowledgeCandidate(id="single-report-refinement", project_name="demo", candidate_type="memory",
                                     statement=report.text, source_report=report),
        point=point, project_root=root, source_refs=[ref], expected_predecessor_entries=[old]))
    assert _run(store.get_entry(old.id, project_name="demo")) is None
    rows = _run(store.list_entries("demo"))
    assert len(rows) == 1
    assert rows[0].id in committed["truth_ids"]
    assert rows[0].source_report == retained
    assert "Ran one check" not in rows[0].statement
    found = _run(search_current_knowledge(backend, project_name="demo", query="local", limit=10))
    assert [row.id for row in found] == committed["truth_ids"]
    assert len(_run(store.list_sources(rows[0].id))) == 1


def test_v9_report_confirmation_runs_actual_final_scope_before_refresh(backend, tmp_path):
    from test_dream_stage4_contract import _ConfirmProvider
    from harness_mem.commands.dream import dream_once

    report, ref = _capture_report(backend, "Alpha cache stays local.")
    root = tmp_path / "confirmation-project"
    root.mkdir()
    ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="report-confirm-before", project_name="demo", candidate_type="memory",
                                     statement=report.text, source_report=report),
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(), "statement": report.render_statement(),
            "topic_path": ["reports"], "claim_kind": "source_report"}], "reason": "Retain this scoped report for maintenance.",
            "final_scope_judgment": _verdict(report)}, project_root=root, source_refs=[ref]))
    store = backend.structured_store.knowledge_store
    before = _run(store.get_entry(ids[0], project_name="demo"))
    provider = _ConfirmProvider()
    run = _run(dream_once(backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider))
    after = _run(store.get_entry(ids[0], project_name="demo"))
    assert after.source_report == before.source_report
    assert after.title == before.title and after.statement == before.statement
    assert len(_run(store.list_entries("demo"))) == 1
    assert provider.calls == 2
    assert provider.manifests[0]["contract_version"] == DREAM_SOURCE_RECHECK_CONTRACT
    assert provider.manifests[1]["contract_version"] == "final-knowledge-scope-v1"
    assert provider.manifests[1]["candidates"][0]["scope_text"] == report_output_scope_text(report)
    assert any(item.result.get("truth_change") == "verification_refreshed" for item in run.items)
    assert run.resolution_status == "resolved"


def test_v9_mixed_report_proposal_final_verification_refines_and_reads_back(backend, tmp_path):
    from dataclasses import replace
    from harness_mem.autonomous.models import AssimilationDecision
    from harness_mem.commands.dream import dream_once
    from test_dream_stage4_contract import _ConfirmProvider

    report, ref = _capture_report(backend, "Alpha cache stays local. Ran one check.")
    root = tmp_path / "mixed-report-project"
    root.mkdir()
    ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="mixed-report-original", project_name="demo", candidate_type="memory",
                                     statement=report.text, source_report=report),
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(), "statement": report.render_statement(),
            "topic_path": ["reports"], "claim_kind": "source_report"}], "reason": "Retain the original scoped report for maintenance.",
            "final_scope_judgment": _verdict(report)}, project_root=root, source_refs=[ref]))
    proposal, retained = _output(report, "Alpha cache", "Alpha cache stays local.")

    class MixedReportProvider(_ConfirmProvider):
        def __init__(self):
            super().__init__()
            self.phases = []

        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            result = super().verify(manifest, runtime_dir=runtime_dir, heartbeat=heartbeat)
            if manifest["contract_version"] != "final-knowledge-scope-v1":
                self.phases.append("source")
                self.source_result = result
                original = manifest["candidates"][0]
                assert original["source_report"] == report.model_dump(mode="json")
                assert original["scope_text"] == report.text
                classification = _original_report_classification(report,
                    [ReportOmission(text=" Ran one check.", classification="temporary_context")])
                return replace(result, decision=CandidateVerificationDecision(points=[classification.model_dump(mode="json")]))
            self.phases.append("final")
            row = manifest["candidates"][0]
            assert row["scope_text"] == report_output_scope_text(retained)
            assert row["source_report"] == retained.model_dump(mode="json")
            assert row["sources"][0]["role"] == "assistant"
            assert row["update_context"]["predecessors"][0]["statement"] == report.render_statement()
            from test_report_original_inventory import native_vote, expand
            return replace(result, decision=expand(manifest, native_vote(manifest)))

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            self.phases.append("proposal")
            original = manifest["verified_candidates"][0]
            assert original["semantic_support"] == "supported"
            assert original["source_report"] == report.model_dump(mode="json")
            return replace(self.source_result, decision=AssimilationDecision.model_validate({"points": [{
                "candidate_id": original["candidate_id"], "disposition": "refine",
                "matched_truth_handles": [manifest["current_truth"][0]["handle"]],
                "report_outputs": [proposal.model_dump(mode="json")],
                "report_omissions": [{"text": " Ran one check.", "classification": "temporary_context"}],
                "reason": "Propose retaining the account with every attribution limit and no run receipt.",
            }]}))

    provider = MixedReportProvider()
    run = _run(dream_once(backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider))
    store = backend.structured_store.knowledge_store
    assert _run(store.get_entry(ids[0], project_name="demo")) is None
    current = _run(store.list_entries("demo"))
    assert len(current) == 1 and current[0].source_report == retained
    assert current[0].source_report.speaker == report.speaker
    assert current[0].source_report.period == report.period
    assert current[0].source_report.source_id == report.source_id
    assert current[0].source_report.source_revision == report.source_revision
    assert "not independently established" in current[0].statement
    assert "Ran one check" not in current[0].statement
    assert provider.phases == ["source", "proposal", "final"]
    found = _run(search_current_knowledge(backend, project_name="demo", query="Alpha cache local", limit=10))
    assert [row.id for row in found] == [current[0].id]
    assert any(item.result.get("truth_change") in {"refine", "replace"} for item in run.items), [
        (item.final_action, item.result, item.reason) for item in run.items]
    assert run.resolution_status == "resolved"
