"""Actual Dream phase orchestration against isolated canonical fixtures."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from test_dream_stage4_contract import backend as backend
from test_dream_stage4_contract import _publish, _result, _run
from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
from harness_mem.commands.dream import dream_once
from harness_mem.core.schemas.knowledge import KnowledgeEntry

OLD = "Cache stays local. The ZXCLI trial completed today."
NEW = "Cache stays local."

class ProposalProvider:
    name = "proposal-fixture"
    def __init__(self, *, failure=None, support="supported"):
        self.failure = failure
        self.support = support
        self.phases = []
        self.final_manifest = None

    def assimilate(self, manifest, **kwargs):
        self.phases.append("assimilate")
        assert manifest["final_scope_required"]
        candidate = manifest["verified_candidates"][0]
        return _result(AssimilationDecision.model_validate({"points": [{
            "candidate_id": candidate["candidate_id"], "disposition": "refine",
            "matched_truth_handles": [manifest["current_truth"][0]["handle"]],
            "knowledge_items": [{"title": "Cache rule", "statement": NEW,
                                 "topic_path": ["cache"], "claim_kind": "implementation_fact"}],
            "reason": "Retain the continuing cache rule and remove the trial receipt."
        }]}))

    def verify(self, manifest, **kwargs):
        self.phases.append("verify")
        final = manifest["contract_version"] == "final-knowledge-scope-v1"
        if final:
            self.final_manifest = manifest
        points = []
        for row in manifest["candidates"]:
            def segment(text, temporary=False):
                return dict(text=text,
                source_use="task_context" if temporary else "reusable_knowledge",
                future_scope="session_only" if temporary else "durable", standalone=True,
                content_role="temporary_context" if temporary else "claim", source_support="supported")
            point = dict(candidate_index=row["candidate_index"], semantic_support="supported",
                         future_scope="durable", source_use="reusable_knowledge",
                         reason="Check the complete source against the exact proposed text.",
                         scope_segments=[segment(row["scope_text"])])
            if not final:
                point["semantic_support"] = self.support
                point["scope_segments"] = [segment("Cache rule\n" + NEW), segment(" The ZXCLI trial completed today.", True)]
                if self.support == "partial":
                    point["scope_segments"][1].update(source_support="unsupported", content_role="claim",
                                                       source_use="unclear", future_scope="unclear")
            elif self.failure != "missing_meaning":
                context = row["update_context"]
                point["update_meaning_judgment"] = dict(
                    relationship="drops_applicable_meaning" if self.failure == "drops" else "preserves_applicable_meaning",
                    predecessor_conditions=[], predecessor_statements=[target["statement"] for target in context["predecessors"]],
                    predecessor_versions=[target["version"] for target in context["predecessors"]],
                    successor_statements=[item["statement"] for item in context["successors"]],
                    basis="The standing rule remains complete and only a trial receipt is removed.")
            points.append(point)
        return _result(CandidateVerificationDecision.model_validate({"points": points}))

@pytest.mark.parametrize("failure", [None, "missing_meaning", "drops"])
@pytest.mark.parametrize("support", ["supported", "partial"])
def test_dream_really_proposes_then_verifies_then_commits(backend, failure, support):
    entry = KnowledgeEntry(id="proposal-old", project_name="demo", title="Cache rule", statement=OLD, module_path=["cache"])
    root, path, original = _publish(backend, entry, source_text=NEW if support == "partial" else OLD)
    provider = ProposalProvider(failure=failure, support=support)
    run = _run(dream_once(backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider))
    assert provider.phases == ["verify", "assimilate", "verify"] + (
        ["assimilate", "verify"] if failure else [])
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    if failure:
        assert [(row.id, row.statement) for row in rows] == [(entry.id, OLD)]
        assert run.resolution_status == "unresolved"
    else:
        assert [row.statement for row in rows] == [NEW]
        assert rows[0].id != entry.id
        assert run.resolution_status == "resolved"
        assert any(item.result.get("truth_change") == "refine" for item in run.items)
    assert provider.final_manifest["candidates"][0]["sources"][0]["content"] == path.read_text(encoding="utf-8")
    notes = "\n".join(run.notes or [])
    assert OLD not in notes and NEW not in notes
    receipts = [json.loads(note.split(": ", 1)[1]) for note in run.notes or [] if note.startswith("dream verification receipt: ")]
    assert [item["phase"] for item in receipts] == provider.phases
    assert sum(item["results"][0]["total_tokens"] for item in receipts) == (10 if failure else 6)


def test_four_proposals_share_calls_and_commit_before_deadline_yield(backend, monkeypatch):
    import harness_mem.commands.dream as dream_module
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(dream_module, "_now", lambda: clock[0])
    originals = [KnowledgeEntry(id=f"batch-{index}", project_name="demo", title=f"Rule {index}",
        statement=f"Cache-{index} stays local. Trial completed today.", module_path=[f"module-{index}"])
        for index in range(5)]
    root, _, _ = _publish(backend, *originals)

    class BatchProvider(ProposalProvider):
        def assimilate(self, manifest, **kwargs):
            self.phases.append("assimilate")
            self.last_candidate_count = len(manifest["verified_candidates"])
            points = []
            for candidate in manifest["verified_candidates"]:
                identity = candidate["candidate_id"].removeprefix("dream:")
                target = next(row for row in manifest["current_truth"] if row["id"] == identity)
                points.append({"candidate_id": candidate["candidate_id"], "disposition": "refine",
                    "matched_truth_handles": [target["handle"]],
                    "knowledge_items": [{"title": target["title"],
                        "statement": target["statement"].split(" Trial")[0],
                        "topic_path": target["topic_path"], "claim_kind": "implementation_fact"}],
                    "reason": "Keep each standing cache rule without its temporary trial receipt."})
            return _result(AssimilationDecision.model_validate({"points": points}))

        def verify(self, manifest, **kwargs):
            self.phases.append("verify")
            points = []
            final = manifest["contract_version"] == "final-knowledge-scope-v1"
            for row in manifest["candidates"]:
                def segment(text, temporary=False):
                    return dict(text=text, source_use="task_context" if temporary else "reusable_knowledge",
                        future_scope="session_only" if temporary else "durable", standalone=True,
                        content_role="temporary_context" if temporary else "claim", source_support="supported")
                point = dict(candidate_index=row["candidate_index"], semantic_support="supported",
                    future_scope="durable", source_use="reusable_knowledge", reason="Read exact complete source and scoped update.",
                    scope_segments=[segment(row["scope_text"])])
                if final:
                    context = row["update_context"]
                    point["update_meaning_judgment"] = dict(relationship="preserves_applicable_meaning",
                        predecessor_conditions=[], predecessor_statements=[item["statement"] for item in context["predecessors"]],
                        predecessor_versions=[item["version"] for item in context["predecessors"]],
                        successor_statements=[item["statement"] for item in context["successors"]],
                        basis="Every substantive rule is retained; only the named trial receipt is removed.")
                else:
                    point["scope_segments"] = [segment(row["scope_text"].split(" Trial")[0]), segment(" Trial completed today.", True)]
                points.append(point)
            if final:
                clock[0] += timedelta(seconds=121)
            return _result(CandidateVerificationDecision.model_validate({"points": points}))

    provider = BatchProvider()
    first = _run(dream_once(backend, project_name="demo", project_root=root, source="agent",
        semantic_provider=provider, reflection_job_id="batch-deadline", deadline=clock[0] + timedelta(seconds=120)))
    assert provider.phases == ["verify", "assimilate", "verify"]
    assert provider.last_candidate_count == 4
    assert first.status == "continuing"
    assert len(first.items) == 4
    assert all(item.final_action == "applied" for item in first.items)
    assert all("knowledge_items" not in proof["point"] for proof in first.continuation["verification"].values())
    second = _run(dream_once(backend, project_name="demo", project_root=root, source="agent",
        semantic_provider=provider, reflection_job_id="batch-deadline", deadline=clock[0] + timedelta(seconds=120)))
    assert second.status in {"completed", "continuing"}
    assert provider.phases == ["verify", "assimilate", "verify"] * 2
    assert len(second.items) == 5
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(rows) == 5 and all("Trial" not in row.statement for row in rows)


def test_invalid_proposal_records_owner_locations_without_private_output(backend):
    entry = KnowledgeEntry(id="proposal-invalid-target", project_name="demo", title="Cache rule", statement=OLD, module_path=["cache"])
    root, _, _ = _publish(backend, entry)
    class InvalidProposal(ProposalProvider):
        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            result.decision.points[0].matched_truth_handles = ["unavailable-handle"]
            result.decision.points[0].reason = "PRIVATE_PROPOSAL_REASON_MUST_NOT_PERSIST"
            return result
    provider = InvalidProposal()
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert provider.phases == ["verify", "assimilate"]
    assert result.resolution_status == "unresolved"
    notes = "\n".join(result.notes or [])
    assert "PRIVATE_PROPOSAL_REASON" not in notes
    rejected = [json.loads(note.split(": ", 1)[1]) for note in result.notes or [] if note.startswith("dream proposal rejected: ")]
    assert rejected[0]["code"] == "common_normalization_failed"
    assert any("separated_assimilation.py:validate_separated_assimilation_decision" in location
               for location in rejected[0]["failure_details"]["exception_locations"])
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [(row.id, row.statement) for row in rows] == [(entry.id, OLD)]


@pytest.mark.parametrize("condition,accepted", [(NEW, True), ("Caching remains on device.", False)])
def test_final_condition_membership_keeps_existing_gate_and_safe_reason(backend, condition, accepted):
    entry = KnowledgeEntry(id="literal-condition", project_name="demo", title="Cache rule",
                           statement=OLD, module_path=["cache"])
    root, _, _ = _publish(backend, entry)

    class ConditionProvider(ProposalProvider):
        def verify(self, manifest, **kwargs):
            result = super().verify(manifest, **kwargs)
            if manifest["contract_version"] == "final-knowledge-scope-v1":
                for point in result.decision.points:
                    point.update_meaning_judgment.predecessor_conditions = [condition]
            return result

    result = _run(dream_once(backend, project_name="demo", project_root=root,
                            semantic_provider=ConditionProvider()))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.statement for row in rows] == ([NEW] if accepted else [OLD])
    rejected = [json.loads(note.split(": ", 1)[1]) for note in result.notes or []
                if note.startswith("dream proposal rejected: ")]
    if accepted:
        assert not rejected
    else:
        assert rejected[0]["reason_code"] == "final_update_meaning_incomplete"
        assert rejected[0]["candidate_id"] == "dream:literal-condition"
        assert condition not in json.dumps(rejected)
