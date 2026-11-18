"""Real isolated Dream orchestration restores same-source omitted evidence."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
from harness_mem.autonomous.provider import _build_assimilation_prompt
from harness_mem.commands.dream import dream_once
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.core.schemas.knowledge import KnowledgeCandidate
from harness_mem.read_knowledge import search_current_knowledge
from test_dream_stage4_contract import backend as backend, _capture_report, _output, _result, _run
from test_dream_rendered_report_proposals import REPORT, RETAINED, TEMPORARY, segment
from test_report_original_inventory import native_vote, expand
from test_report_single_commit import _verdict


MODE = "source_backed_same_topic_revision"
DIAGNOSIS = "The same native executable starts without input; only the diagnostic child PATH was shortened."


@pytest.fixture
def revision_case(backend):
    original_source, ref = _capture_report(backend, REPORT + " " + DIAGNOSIS)
    report = original_source.model_copy(update={"text": REPORT})
    root = Path(backend.data_dir) / "source-backed-dream-project"
    root.mkdir()
    old_ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="old-report", project_name="demo", candidate_type="memory",
            statement=report.text, source_report=report), project_root=root, source_refs=[ref],
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(),
            "statement": report.render_statement(), "topic_path": ["reports"], "claim_kind": "source_report"}],
            "reason": "Retain this source-scoped account.", "final_scope_judgment": _verdict(report)}))
    old = _run(backend.structured_store.knowledge_store.get_entry(old_ids[0], project_name="demo"))
    output, written = _output(report, report.render_title(), RETAINED + " " + DIAGNOSIS)
    return backend, root, old, output, written


class RevisionProvider:
    name = "isolated-source-backed-report"

    def __init__(self, case, failure=None):
        self.case, self.failure = case, failure
        self.proposals = []
        self.finals = []

    def verify(self, manifest, **_kwargs):
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            self.finals.append(copy.deepcopy(manifest))
            native = native_vote(manifest)
            for point in native["points"]:
                if self.failure == "unsupported":
                    point["semantic_support"] = "partial"
                    point["scope_segments"][0]["source_support"] = "unsupported"
                elif self.failure == "drops_meaning":
                    point["update_meaning_judgment"]["relationship"] = "drops_applicable_meaning"
                elif self.failure == "missing_original_vote":
                    point["update_meaning_judgment"].pop("report_preservation", None)
            return _result(expand(manifest, native))
        points = []
        for row in manifest["candidates"]:
            assert row["scope_text"] == REPORT
            assert DIAGNOSIS in row["sources"][0]["content"]
            points.append(dict(candidate_index=row["candidate_index"], semantic_support="supported",
                future_scope="unclear", source_use="reusable_knowledge",
                reason="Keep the durable account distinct from its temporary run receipt.",
                scope_segments=[segment(RETAINED), segment(TEMPORARY, temporary=True)],
                claim_units=[dict(first_segment=0, end_segment_exclusive=1, standalone=True,
                    source_support="supported", source_use="reusable_knowledge", future_scope="durable")]))
        return _result(CandidateVerificationDecision.model_validate({"points": points}))

    def assimilate(self, manifest, **_kwargs):
        self.proposals.append(copy.deepcopy(manifest))
        incoming = manifest["verified_candidates"][0]
        original = manifest["maintenance_candidates"][0]["scope_verification"]
        assert manifest["report_revision_modes"][incoming["candidate_id"]] == MODE
        assert original["future_scope"] == "unclear"
        assert "".join(part["text"] for part in original["scope_segments"]) == REPORT
        output = self.case[3].model_dump(mode="json")
        return _result(AssimilationDecision.model_validate({"points": [{
            "candidate_id": incoming["candidate_id"], "disposition": "refine",
            "matched_truth_handles": [manifest["current_truth"][0]["handle"]],
            "report_outputs": [output], "report_omissions": [],
            "reason": "Restore the same-source diagnosis and retain its original account boundary."}]}))


@pytest.mark.parametrize("failure", [None, "unsupported", "drops_meaning", "missing_original_vote"])
def test_actual_dream_revision_preserves_old_classification_and_uses_final_canonical_owner(revision_case, failure):
    backend, root, old, _output_proposal, written = revision_case
    provider = RevisionProvider(revision_case, failure=failure)
    run = _run(dream_once(backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider))
    assert provider.proposals and provider.finals
    inventory = provider.finals[0]["candidates"][0]["update_context"]["report_preservation_inventory"]
    assert inventory["mode"] == "full_revision"
    assert inventory["segments"][1]["future_scope"] == "session_only"
    store = backend.structured_store.knowledge_store
    current = _run(store.list_entries("demo", project_root=root))
    if failure:
        assert [(entry.id, entry.statement) for entry in current] == [(old.id, old.statement)]
        assert run.resolution_status == "unresolved"
    else:
        assert len(current) == 1 and current[0].id != old.id
        assert current[0].source_report == written
        assert _run(store.get_entry(old.id, project_name="demo")) is None
        assert run.resolution_status == "resolved"
        found = _run(search_current_knowledge(backend, project_name="demo", query="diagnostic child PATH", limit=10))
        assert current[0].id in {entry.id for entry in found}
        assert "source_backed_same_topic_revision" in str(run.notes) or any(
            item.result.get("truth_change") in {"refine", "replace"} for item in run.items)


def test_native_prompt_distinguishes_runtime_revision_from_default_literal_cleanup():
    manifest = dict(contract_version="separated-knowledge-assimilation-v1", verified_candidates=[],
        current_truth=[], maintenance_candidates=[{"candidate_id": "candidate"}])
    literal = _build_assimilation_prompt(manifest)
    assert "Do not paraphrase, insert connectors" in literal
    assert "New wording is permitted only in this mode" not in literal
    manifest["report_revision_modes"] = {"candidate": MODE}
    revision = _build_assimilation_prompt(manifest)
    assert "New wording is permitted only in this mode" in revision
    assert "complete original claim/qualifier inventory" in revision
    assert "Do not supply replacement prose through knowledge_items" in revision
