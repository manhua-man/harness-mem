"""Existing coverage stages compare current memory and bind additive conditions."""

from dataclasses import replace

import pytest

from harness_mem.autonomous.models import AssimilationDecision, NativeFinalScopeDecision
from harness_mem.commands.dream_source_coverage import _entry_version_snapshot
from harness_mem.core.schemas.knowledge import AssimilationDecision as StoredDecision
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import CoverageProvider, _cover, coverage as coverage, run
from test_dream_stage4_contract import _result


def publish_comparison(data):
    backend, root, _job, entry, *_rest = data
    store = backend.structured_store.knowledge_store
    duplicate = KnowledgeEntry(id="already-covered-elsewhere", project_name="demo",
        module_path=["daily-entry"], title="Existing scoped condition",
        statement="During this daily-entry repair, do not add acceptance rituals.")
    candidate = KnowledgeCandidate(id="comparison-fixture", project_name="demo",
        candidate_type="memory", statement=duplicate.statement)
    refs = [ProjectKnowledgeSourceRef(label="Original user", target=source.locator,
        kind=source.source_kind, digest=source.content_sha256)
        for source in run(store.list_sources(entry.id))]
    run(store.save_candidate(candidate))
    run(store.apply_current_change(candidate_before=candidate,
        candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=StoredDecision(id="comparison-fixture-publish", project_name="demo",
            candidate_id=candidate.id, disposition="add", canonical_truth_ids=[duplicate.id],
            reason="Independent isolated fixture."), added_entries=[duplicate],
        predecessor_entries=[], source_refs_by_entry={duplicate.id: refs}))
    run(store.cleanup_candidate(candidate.id))
    return duplicate


def test_related_truth_stays_comparison_without_mutation_handles(coverage):
    duplicate = publish_comparison(coverage)
    before = duplicate.to_dict()

    class Provider(CoverageProvider):
        def assimilate(self, manifest, **kwargs):
            self.calls.append("assimilate")
            assert all(row["statement"] != duplicate.statement for row in manifest["current_truth"])
            scope = manifest["source_coverage"]
            compared = next(row for row in scope["comparison_current_truth"] if row["id"] == duplicate.id)
            assert compared["statement"] == duplicate.statement
            assert "handle" not in compared and compared["comparison_only"] is True
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": manifest["verified_candidates"][0]["candidate_id"],
                "disposition": "no_write", "matched_truth_handles": [],
                "reason": "The independently compared current memory already covers this point."}]}))

    provider = Provider()
    run(_cover(coverage, provider))
    backend, root, *_rest = coverage
    entries = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert {row.id for row in entries} == {"narrow-successor", duplicate.id}
    assert run(backend.structured_store.knowledge_store.get_entry(
        duplicate.id, project_name="demo", project_root=root)).to_dict() == before
    assert coverage[-2]["source_coverage"][coverage[4].source_id]["status"] == "no_write"


def test_comparison_id_never_becomes_an_assimilation_target(coverage):
    duplicate = publish_comparison(coverage)

    class Provider(CoverageProvider):
        def assimilate(self, manifest, **kwargs):
            self.calls.append("assimilate")
            assert all(row["handle"] != duplicate.id for row in manifest["current_truth"])
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": manifest["verified_candidates"][0]["candidate_id"],
                "disposition": "confirm", "matched_truth_handles": [duplicate.id],
                "reason": "Attempt an unavailable comparison target handle."}]}))

    run(_cover(coverage, Provider()))
    backend, root, *_rest = coverage
    assert {row.id for row in run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))} == {
        "narrow-successor", duplicate.id}


@pytest.mark.parametrize("missing", [False, True])
def test_condition_bearing_add_uses_existing_native_final_stage(coverage, missing):
    condition = "During this daily-entry repair"

    class Provider(CoverageProvider):
        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            point = result.decision.points[0].model_copy(update={"retained_conditions": [condition]})
            return replace(result, decision=result.decision.model_copy(update={"points": [point]}))

        def verify(self, manifest, **kwargs):
            if manifest["contract_version"] != "final-knowledge-scope-v1":
                return super().verify(manifest, **kwargs)
            self.calls.append("final_verify")
            rows = []
            for row in manifest["candidates"]:
                context = row["update_context"]
                assert context["disposition"] == "add" and context["predecessors"] == []
                assert context["retained_conditions"] == [condition]
                statement = row["statement"]
                proof = None if missing else {
                    "relationship": "preserves_applicable_meaning", "inventory_complete": True,
                    "condition_spans": [{"successor_index": 0, "char_start": statement.index(condition),
                        "char_end": statement.index(condition) + len(condition)}],
                    "undecided_span": None,
                    "basis": "Independently read the scoped original source and exact final output."}
                rows.append({"candidate_index": row["candidate_index"], "semantic_support": "supported",
                    "future_scope": "durable", "source_use": "standing_decision",
                    "reason": "The complete original user source establishes this scoped condition.",
                    "scope_segments": [{"text": row["scope_text"], "source_use": "standing_decision",
                        "future_scope": "durable", "standalone": True, "content_role": "claim",
                        "source_support": "supported"}], "update_meaning_judgment": proof})
            return _result(NativeFinalScopeDecision.model_validate({"points": rows}).as_verification(manifest))

    provider = Provider()
    run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    assert state["status"] == ("unresolved" if missing else "applied")
    backend, root, *_rest = coverage
    entries = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(entries) == (1 if missing else 2)
    assert _entry_version_snapshot(next(row for row in entries if row.id == "narrow-successor"))
