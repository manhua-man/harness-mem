"""Structural report failures receive one bounded correction, never admission."""
import copy
import json

import pytest

from test_dream_stage4_contract import backend as backend
from test_dream_stage4_contract import _capture_report, _output, _publish, _result, _run
from test_report_single_commit import _verdict
from test_dream_proposal_execution import OLD, NEW
from test_dream_proposal_repair import RevisionProvider
from test_dream_proposal_group_isolation import prepared, proposal

from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
from harness_mem.commands.dream import dream_once, _normalize_dream_proposal_groups
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.source_report import ReportQualifier
from harness_mem.read_knowledge import search_current_knowledge


@pytest.mark.parametrize("revision,final_drops,accepted", [
    ("correct", False, True), ("unchanged", False, False),
    ("defer", False, False), ("correct", True, False),
])
def test_report_qualifier_structural_failure_corrects_only_through_full_final_gate(
    backend, tmp_path, revision, final_drops, accepted,
):
    report, ref = _capture_report(backend, "Alpha cache stays local. Ran one check.")
    root = tmp_path / "report-project"
    root.mkdir()
    ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="structural-original", project_name="demo", candidate_type="memory",
            statement=report.text, source_report=report), project_root=root, source_refs=[ref],
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(),
            "statement": report.render_statement(), "topic_path": ["reports"], "claim_kind": "source_report"}],
            "reason": "Retain the complete fixture report with native source authority.",
            "final_scope_judgment": _verdict(report)}))
    output, retained = _output(report, "Alpha cache", "Alpha cache stays local.")

    class Provider:
        name = "structural-report-fixture"

        def __init__(self):
            self.phases = []
            self.repairs = []
            self.final_count = 0

        def assimilate(self, manifest, **kwargs):
            self.phases.append("assimilate")
            repair = manifest.get("proposal_repair")
            if repair:
                self.repairs.append(copy.deepcopy(manifest))
            candidate = manifest["verified_candidates"][0]
            truth = next(item for item in manifest["current_truth"] if item["id"] == ids[0])
            if repair and revision == "defer":
                point = dict(candidate_id=candidate["candidate_id"], disposition="defer",
                    matched_truth_handles=[], reason="Keep the original because this correction is unavailable.")
            else:
                item = output.model_copy(deep=True)
                if not repair or revision == "unchanged":
                    item.qualifiers = [ReportQualifier(text="PRIVATE_MISSING_REPORT_QUALIFIER",
                        source_support="supported", independently_useful=True)]
                point = dict(candidate_id=candidate["candidate_id"], disposition="refine",
                    matched_truth_handles=[truth["handle"]], report_outputs=[item.model_dump(mode="json")],
                    report_omissions=[dict(text=" Ran one check.", classification="temporary_context")],
                    reason="PRIVATE_STRUCTURAL_DRAFT_REASON retain the original report boundary.")
            return _result(AssimilationDecision.model_validate({"points": [point]}))

        def verify(self, manifest, **kwargs):
            self.phases.append("verify")
            final = manifest["contract_version"] == "final-knowledge-scope-v1"
            if final:
                from test_native_final_scope_transport import native_payload
                from test_report_original_inventory import expand

                native = native_payload(manifest)
                for vote, row in zip(native["points"], manifest["candidates"]):
                    self.final_count += 1
                    assert row["source_report"] == retained.model_dump(mode="json")
                    assert row["sources"][0]["role"] == "assistant"
                    context = row["update_context"]
                    inventory = context["report_preservation_inventory"]
                    assert context["predecessors"][0]["source_report"] == report.model_dump(mode="json")
                    assert inventory["mode"] == "literal_projection"
                    units = []
                    for index, unit in enumerate(inventory["units"]):
                        original_text = report.text[unit["start"]:unit["end"]]
                        if unit["future_scope"] == "session_only":
                            assert original_text == " Ran one check."
                            assert any(omission["start"] <= unit["start"] and unit["end"] <= omission["end"]
                                       for omission in inventory["omissions"])
                            units.append(dict(unit_index=index, verdict="disposable", successor_spans=[]))
                        else:
                            assert original_text == "Alpha cache stays local."
                            offset = retained.text.index(original_text)
                            units.append(dict(unit_index=index, verdict="preserved", successor_spans=[
                                dict(successor_index=0, char_start=offset, char_end=offset + len(original_text))]))
                    assert len(inventory["omissions"]) == 1
                    omission = inventory["omissions"][0]
                    assert report.text[omission["start"]:omission["end"]] == " Ran one check."
                    meaning = vote["update_meaning_judgment"]
                    meaning["relationship"] = "drops_applicable_meaning" if final_drops else "preserves_applicable_meaning"
                    statement = context["successors"][0]["statement"]
                    offset = statement.index(retained.text)
                    meaning["condition_spans"] = [dict(successor_index=0, char_start=offset,
                                                        char_end=offset + len(retained.text))]
                    meaning["report_preservation"] = dict(inventory_complete=True, units=units, omissions=[
                        dict(omission_index=0, claim="not_applicable", evidence="not_applicable", causality="not_applicable",
                             boundary="not_applicable", permission="not_applicable", scope="not_applicable")])
                return _result(expand(manifest, native))
            points = []
            for row in manifest["candidates"]:
                segments = [dict(text="Alpha cache stays local.", source_support="supported",
                    source_use="reusable_knowledge", future_scope="durable", content_role="claim", standalone=True),
                    dict(text=" Ran one check.", source_support="supported", source_use="task_context",
                    future_scope="session_only", content_role="temporary_context", standalone=True)]
                point = dict(candidate_index=row["candidate_index"], semantic_support="supported",
                    source_use="reusable_knowledge", future_scope="durable", scope_segments=segments,
                    reason="Independently verify the complete reopened fixture source and output.")
                point["claim_units"] = [dict(first_segment=0, end_segment_exclusive=1, standalone=True,
                    source_support="supported", source_use="reusable_knowledge", future_scope="durable")]
                points.append(point)
            return _result(CandidateVerificationDecision.model_validate({"points": points}))

    provider = Provider()
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert len(provider.repairs) == 1
    feedback = provider.repairs[0]["proposal_repair"]
    assert feedback["attempt"] == 1
    assert feedback["allowed_target_ids"] == ids
    rejection = feedback["previous_rejections"][0]
    assert rejection["reason_code"] == "report_output_qualifier_missing"
    assert rejection["final_judgments"] is None
    assert "proposed_point" in rejection and not rejection.get("payload")
    assert rejection["proposed_point"]["report_outputs"][0]["qualifiers"][0]["text"] == "PRIVATE_MISSING_REPORT_QUALIFIER"
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(rows) == 1
    if accepted:
        assert rows[0].source_report == retained
        assert rows[0].source_report.same_account_source(report)
        assert rows[0].source_report.period == report.period
        assert rows[0].source_report.source_revision == report.source_revision
        assert _run(backend.structured_store.knowledge_store.get_entry(ids[0], project_name="demo")) is None
        found = _run(search_current_knowledge(backend, project_name="demo", query="Alpha cache local", limit=10))
        assert [item.id for item in found] == [rows[0].id]
        assert provider.final_count == 1
    else:
        assert rows[0].id == ids[0] and rows[0].source_report == report
    assert provider.phases.count("assimilate") == 2
    assert provider.final_count == (1 if revision == "correct" else 0)
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "PRIVATE_MISSING_REPORT_QUALIFIER" not in serialized
    assert "PRIVATE_STRUCTURAL_DRAFT_REASON" not in serialized


def test_contradicted_ordinary_structural_failure_defer_cannot_delete_original(backend):
    entry = KnowledgeEntry(id="needs-revision", project_name="demo", title="Cache rule", statement=OLD,
                           module_path=["cache"])
    root, _, _ = _publish(backend, entry, source_text=NEW)

    class Provider(RevisionProvider):
        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            if not manifest.get("proposal_repair"):
                point = result.decision.points[0]
                point.matched_truth_handles *= 2  # Known own handle, local common-validator error.
            return result

    provider = Provider("defer", support="contradicted")
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [(item.id, item.statement) for item in rows] == [(entry.id, OLD)]
    assert len(provider.repair_manifests) == 1
    assert result.resolution_status == "unresolved"
    assert not any(item.result.get("truth_change") == "delete" for item in result.items)


def test_unknown_handle_contradicted_writing_is_not_retried_or_deleted(backend):
    entry = KnowledgeEntry(id="needs-revision", project_name="demo", title="Cache rule", statement=OLD,
                           module_path=["cache"])
    root, _, _ = _publish(backend, entry, source_text=NEW)

    class Provider(RevisionProvider):
        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            result.decision.points[0].matched_truth_handles = ["unavailable-handle"]
            return result

    provider = Provider("correct", support="contradicted")
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [(item.id, item.statement) for item in rows] == [(entry.id, OLD)]
    assert provider.repair_manifests == []
    assert provider.phases == ["verify", "assimilate"]
    assert result.resolution_status == "unresolved"


def test_structural_and_final_rejections_share_one_round_and_keep_accepted_neighbor(backend):
    subjects = {"structural": "Queue", "final": "Cache", "accepted": "Media"}
    entries = [KnowledgeEntry(id=identity, project_name="demo", title=subject + " rule",
                             statement=OLD.replace("Cache", subject), module_path=[identity])
               for identity, subject in subjects.items()]
    root, _, _ = _publish(backend, *entries)

    class Provider(RevisionProvider):
        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            if not manifest.get("proposal_repair"):
                for point in result.decision.points:
                    if point.candidate_id == "dream:structural":
                        point.matched_truth_handles *= 2
            else:
                for point in result.decision.points:
                    if point.candidate_id == "dream:structural":
                        point.knowledge_items[0].statement = "Queue stays local."
            return result

    provider = Provider("correct")
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert len(provider.repair_manifests) == 1
    manifest = provider.repair_manifests[0]
    assert {item["id"] for item in manifest["current_truth"]} == {item.id for item in entries}
    assert {item["candidate_id"] for item in manifest["verified_candidates"]} == {"dream:structural", "dream:final"}
    feedback = manifest["proposal_repair"]["previous_rejections"]
    assert len(feedback) == 2
    assert sum(item["final_judgments"] is None for item in feedback) == 1
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert sorted(item.statement for item in rows) == ["Cache stays local.", "Media stays local.", "Queue stays local."]
    assert result.resolution_status == "resolved"


@pytest.mark.parametrize("invalid", ["cross_group", "unknown_handle", "scope_expansion"])
def test_unsafe_normalization_never_acquires_repair_targets(invalid):
    source, decision = prepared(2), proposal(2)
    if invalid == "unknown_handle":
        decision.points[0].matched_truth_handles = ["not-present"]
    else:
        decision.points[0].matched_truth_handles.append("K1")
    feedback = []
    payloads = _normalize_dream_proposal_groups(source, decision,
        identities={"entry-0": "dream:entry-0", "entry-1": "dream:entry-1"},
        groups=[["entry-0", "entry-1"]] if invalid == "scope_expansion" else [["entry-0"], ["entry-1"]],
        report_ids=set(), receipts=[], repair_feedback=feedback,
        mutable_target_ids={"entry-0"} if invalid == "scope_expansion" else None)
    assert not any(point["candidate_id"] == "dream:entry-0" for point, _ in payloads)
    assert not feedback  # Global/cross-group/scope-expanding failures are not corrective authority.
