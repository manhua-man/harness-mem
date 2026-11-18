"""A single source-bound revision reuses the original final gate and account."""
import json

import pytest

from test_dream_stage4_contract import backend as backend
from test_dream_stage4_contract import _publish, _run, _result
from test_dream_proposal_execution import OLD, NEW, ProposalProvider
from test_dream_proposal_group_isolation import prepared, proposal
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.dream import dream_once, _normalize_dream_proposal_groups
from harness_mem.core.schemas.knowledge import KnowledgeEntry

BAD = "Cache stays local. ZXCLI trial completed today."


class RevisionProvider(ProposalProvider):
    def __init__(self, repair="correct", support="supported"):
        super().__init__(support=support)
        self.repair = repair
        self.repair_manifests = []
        self.sources = []

    def assimilate(self, manifest, **kwargs):
        self.phases.append("assimilate")
        repair = manifest.get("proposal_repair")
        if repair:
            self.repair_manifests.append(manifest)
            if self.repair == "unavailable":
                raise ProviderError("fixture call limit reached", kind="unrecoverable",
                                    failure_reason="task_model_budget_calls_exhausted")
        points = []
        for candidate in manifest["verified_candidates"]:
            identity = candidate["candidate_id"].removeprefix("dream:")
            target = next(row for row in manifest["current_truth"] if row["id"] == identity)
            nonwrite = repair and self.repair == "defer"
            statement = (target["statement"].split(" The ZXCLI")[0] if identity == "accepted" else
                         NEW if repair and self.repair == "correct" else BAD)
            points.append(dict(candidate_id=candidate["candidate_id"],
                disposition="defer" if nonwrite else "refine",
                matched_truth_handles=[] if nonwrite else [target["handle"]],
                knowledge_items=[] if nonwrite else [dict(title=target["title"], statement=statement,
                    topic_path=["cache"], claim_kind="implementation_fact")],
                reason="Return the checked rule with the original boundary, never force an output."))
        return _result(AssimilationDecision.model_validate(dict(points=points)))

    def verify(self, manifest, **kwargs):
        result = super().verify(manifest, **kwargs)
        if manifest["contract_version"] != "final-knowledge-scope-v1":
            for point, row in zip(result.decision.points, manifest["candidates"]):
                point.scope_segments[0].text = row["scope_text"].removesuffix(
                    " The ZXCLI trial completed today.")
            return result
        for point, row in zip(result.decision.points, manifest["candidates"]):
            self.sources.append(row["sources"])
            if row["statement"] == BAD:
                durable = dict(text=row["title"] + "\n" + NEW,
                    source_use="reusable_knowledge", future_scope="durable", standalone=True,
                    content_role="claim", source_support="supported")
                temporary = dict(text=" ZXCLI trial completed today.", source_use="task_context",
                    future_scope="session_only", standalone=True, content_role="temporary_context",
                    source_support="supported")
                point.scope_segments = [type(point.scope_segments[0]).model_validate(value)
                                        for value in [durable, temporary]]
        return result


@pytest.mark.parametrize("repair,accepted", [("correct", True), ("unchanged", False), ("defer", False)])
def test_one_revision_reopens_full_sources_and_still_requires_final_scope(backend, repair, accepted):
    entry = KnowledgeEntry(id="needs-revision", project_name="demo", title="Cache rule",
                           statement=OLD, module_path=["cache"])
    root, path, _ = _publish(backend, entry)
    provider = RevisionProvider(repair)
    result = _run(dream_once(backend, project_name="demo", project_root=root,
                            semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.statement for row in rows] == ([NEW] if accepted else [OLD])
    assert len(provider.repair_manifests) == 1  # Never loop an unchanged rejected draft.
    feedback = provider.repair_manifests[0]["proposal_repair"]
    assert feedback["attempt"] == 1
    assert feedback["allowed_target_ids"] == [entry.id]
    rejected = feedback["previous_rejections"][0]
    assert rejected["payload"]["knowledge_items"][0]["statement"] == BAD
    assert rejected["final_judgments"]["points"][0]["scope_segments"][-1]["future_scope"] == "session_only"
    assert all(sources[0]["content"] == path.read_text(encoding="utf-8") for sources in provider.sources)
    assert provider.phases == ["verify", "assimilate", "verify", "assimilate"] + (
        [] if repair == "defer" else ["verify"])
    assert OLD not in "\n".join(result.notes or [])  # Drafts stay ephemeral.
    assert BAD not in "\n".join(result.notes or [])
    if accepted:
        assert result.resolution_status == "resolved"
        assert any(item.result.get("truth_change") == "refine" for item in result.items)
    else:
        assert result.resolution_status == "unresolved"


def test_nonwriting_revision_cannot_fall_back_to_deleting_a_contradicted_original(backend):
    entry = KnowledgeEntry(id="needs-revision", project_name="demo", title="Cache rule",
                           statement=OLD, module_path=["cache"])
    root, _, _ = _publish(backend, entry, source_text=NEW)
    provider = RevisionProvider("defer", support="contradicted")
    result = _run(dream_once(backend, project_name="demo", project_root=root,
                            semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [(row.id, row.statement) for row in rows] == [(entry.id, OLD)]
    assert result.resolution_status == "unresolved"


def test_unavailable_revision_keeps_independent_already_verified_group(backend):
    entries = [KnowledgeEntry(id=identity, project_name="demo",
                             title="Media rule" if identity == "accepted" else "Cache rule",
                             statement=OLD.replace("Cache", "Media") if identity == "accepted" else OLD,
                             module_path=[identity])
               for identity in ["accepted", "needs-revision"]]
    root, _, _ = _publish(backend, *entries)
    provider = RevisionProvider("unavailable")
    result = _run(dream_once(backend, project_name="demo", project_root=root,
                            semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert sorted(row.statement for row in rows) == sorted([OLD, "Media stays local."])
    assert result.resolution_status == "unresolved"
    assert len(provider.repair_manifests) == 1
    manifest = provider.repair_manifests[0]
    assert {row["id"] for row in manifest["current_truth"]} == {row.id for row in entries}
    assert len(manifest["maintenance_candidates"]) == 1
    assert manifest["maintenance_candidates"][0]["candidate_id"] == "dream:needs-revision"
    assert provider.phases == ["verify", "assimilate", "verify", "assimilate"]
    assert any(note.startswith("dream proposal repair unavailable: ") for note in result.notes or [])


def test_revision_cannot_expand_mutation_to_a_readonly_neighbor_inside_same_group():
    source = prepared(2)
    decision = proposal(2)
    decision.points[1].disposition = "defer"
    decision.points[1].matched_truth_handles = []
    decision.points[1].knowledge_items = []
    decision.points[0].matched_truth_handles.append("K1")
    notes = []
    payloads = _normalize_dream_proposal_groups(source, decision,
        identities={"entry-0": "dream:entry-0", "entry-1": "dream:entry-1"},
        groups=[["entry-0", "entry-1"]], report_ids=set(), receipts=notes,
        mutable_target_ids={"entry-0"})
    assert payloads == []
    assert "comparison_group_normalization_failed" in json.dumps(notes)
