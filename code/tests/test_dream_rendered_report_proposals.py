"""Native-shaped rendered report failures reach existing safe proposal owners."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from test_dream_stage4_contract import backend as backend
from test_dream_stage4_contract import _capture_report, _output, _publish, _result, _run
from test_report_single_commit import _verdict
from test_dream_proposal_execution import ProposalProvider, OLD, NEW
from test_report_original_inventory import native_vote, expand
from harness_mem.autonomous.models import (
    AssimilationDecision, CandidateVerificationDecision, DREAM_SOURCE_RECHECK_CONTRACT,
)
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, dispatch_with_task_budget, read_task_budget_receipt,
)
from harness_mem.commands.dream import dream_once, DreamRecheckSignal, _run_source_backed_recheck_group
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.source_report import ReportQualifier, report_output_scope_text
from harness_mem.read_knowledge import search_current_knowledge


REPORT = "Alpha cache stays local. Ran one check."
RETAINED = "Alpha cache stays local."
TEMPORARY = " Ran one check."


@pytest.fixture
def report_case(backend):
    report, ref = _capture_report(backend, REPORT)
    root = Path(backend.data_dir) / "rendered-report-project"
    root.mkdir()
    ids = _run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="rendered-original", project_name="demo", candidate_type="memory",
            statement=report.text, source_report=report), project_root=root, source_refs=[ref],
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(),
            "statement": report.render_statement(), "topic_path": ["reports"], "claim_kind": "source_report"}],
            "reason": "Retain the complete source-scoped fixture account.", "final_scope_judgment": _verdict(report)}))
    before = _run(backend.structured_store.knowledge_store.get_entry(ids[0], project_name="demo"))
    output, retained = _output(report, "Alpha cache", RETAINED)
    return backend, root, report, before, output, retained


def segment(text, *, temporary=False, unsupported=False):
    return dict(text=text, source_support="unsupported" if unsupported else "supported",
        source_use="task_context" if temporary else "reusable_knowledge",
        future_scope="session_only" if temporary else "durable",
        content_role="temporary_context" if temporary else "claim", standalone=True)


class RenderedProvider:
    name = "rendered-report-fixture"
    host_client = "codex"

    def __init__(self, case, *, failure=None):
        self.case = case
        self.failure = failure
        self.phases = []
        self.manifests = []
        self.scopes = []
        self.budget_calls = 0

    def bind_task_budget(self, binding, **kwargs):
        self.task_budget_binding = binding
        self.phase, self.slice = kwargs["phase"], kwargs["slice_id"]

    def charge(self):
        self.scopes.append(self.task_budget_binding.task_scope)
        dispatch_with_task_budget(self.task_budget_binding, phase=self.phase, slice_id=self.slice,
            timeout_seconds=1, transport=lambda _: NativeDispatchResult(status="completed", input_tokens=1,
                output_tokens=1, duration_seconds=.01, usage_exact=True))
        self.budget_calls += 1

    def verify(self, manifest, **kwargs):
        kwargs["heartbeat"]()
        self.charge()
        self.manifests.append(copy.deepcopy(manifest))
        final = manifest["contract_version"] == "final-knowledge-scope-v1"
        proposed = final and any(row.get("update_context") for row in manifest["candidates"])
        self.phases.append("final" if proposed else "rendered" if final else "source")
        points = []
        for row in manifest["candidates"]:
            scope = row["scope_text"]
            support, future = "supported", "durable"
            if not final:
                assert scope == REPORT
                parts = [segment(scope)]
                if self.failure == "original_partial":
                    support = "partial"
                    parts = [segment(RETAINED), segment(TEMPORARY, unsupported=True)]
            elif not proposed:
                assert scope == report_output_scope_text(self.case[2])
                before, after = scope.split(TEMPORARY)
                parts = [segment(before), segment(TEMPORARY, temporary=True), segment(after)]
                future = "unclear"
                if self.failure == "rendered_partial":
                    parts[0]["source_support"] = "unsupported"
                    support = "partial"
                elif self.failure == "confirmation_ok":
                    parts = [segment(scope)]
                    future = "durable"
            else:
                assert row["source_report"] == self.case[-1].model_dump(mode="json")
                assert row["sources"][0]["role"] == "assistant"
                parts = [segment(scope, unsupported=self.failure == "final_partial")]
                if self.failure == "final_partial":
                    support = "partial"
            point = dict(candidate_index=row["candidate_index"], semantic_support=support,
                future_scope=future, source_use="reusable_knowledge", scope_segments=parts,
                reason="Independently compare the complete original account and the exact rendered output.")
            if not final:
                point["claim_units"] = [{"first_segment": 0, "end_segment_exclusive": len(parts),
                    "standalone": True, "source_support": "supported" if support == "supported" else "unclear",
                    "source_use": "reusable_knowledge", "future_scope": "durable"}]
            if proposed:
                context = row["update_context"]
                point["update_meaning_judgment"] = dict(
                    relationship="drops_applicable_meaning" if self.failure == "drops_meaning" else "preserves_applicable_meaning",
                    predecessor_conditions=[], predecessor_statements=[p["statement"] for p in context["predecessors"]],
                    predecessor_versions=[p["version"] for p in context["predecessors"]],
                    successor_statements=[p["statement"] for p in context["successors"]],
                    basis="Preserve the original speaker, source period and useful cache account; omit only a run receipt.")
            points.append(point)
        if proposed:
            native = native_vote(manifest)
            for projected, original in zip(native["points"], points):
                for key in ("semantic_support", "future_scope", "source_use", "reason", "scope_segments"):
                    projected[key] = original[key]
                projected["update_meaning_judgment"]["relationship"] = original["update_meaning_judgment"]["relationship"]
            return _result(expand(manifest, native))
        return _result(CandidateVerificationDecision.model_validate({"points": points}))

    def assimilate(self, manifest, **kwargs):
        kwargs["heartbeat"]()
        self.charge()
        self.phases.append("proposal")
        self.manifests.append(copy.deepcopy(manifest))
        candidate = manifest["verified_candidates"][0]
        maintenance = manifest["maintenance_candidates"][0]
        if self.failure != "original_partial":
            feedback = maintenance["rendered_confirmation_feedback"]
            assert feedback["kind"] == "runtime_rendered_confirmation_not_source_evidence"
            assert "not source evidence" in feedback["instruction"]
            assert feedback["judgment"]["future_scope"] == "unclear"
            assert candidate["source_report"] == self.case[2].model_dump(mode="json")
            # The original complete classification is not rewritten to turn
            # this independent feedback into source support.
            assert maintenance["scope_verification"]["semantic_support"] == "supported"
            assert "".join(p["text"] for p in maintenance["scope_verification"]["scope_segments"]) == REPORT
        if self.failure in {"rendered_partial", "original_partial"}:
            assert candidate["semantic_support"] == "partial"
        else:
            assert candidate["semantic_support"] == "supported"
        if self.failure == "defer":
            point = dict(candidate_id=candidate["candidate_id"], disposition="defer",
                matched_truth_handles=[], reason="Keep the existing account because no safe omitted claim is available.")
        else:
            output = self.case[-2].model_copy(deep=True)
            if self.failure == "drop_qualifier":
                output.qualifiers = [ReportQualifier(text="PRIVATE_REQUIRED_QUALIFIER", source_support="unsupported",
                                                     independently_useful=True)]
            point = dict(candidate_id=candidate["candidate_id"], disposition="refine",
                matched_truth_handles=[manifest["current_truth"][0]["handle"]],
                report_outputs=[output.model_dump(mode="json")],
                report_omissions=[dict(text=TEMPORARY, classification="temporary_context")],
                reason="Retain the source-bound complete cache account and omit only the temporary run receipt.")
        return _result(AssimilationDecision.model_validate({"points": [point]}))


def invoke(case, provider):
    return _run(dream_once(case[0], project_name="demo", project_root=case[1], semantic_provider=provider,
        config=MergedConfig(), host_client="codex",
        maintenance_scope={"trigger_id": "fixture-original", "dispatch_generation": "fixture-generation"}))


def test_durable_body_rendered_mixed_proposes_independently_verifies_commits_and_reads_back(report_case):
    backend, root, report, before, _output_item, retained = report_case
    provider = RenderedProvider(report_case)
    result = invoke(report_case, provider)
    assert provider.phases == ["source", "rendered", "proposal", "final"]
    assert _run(backend.structured_store.knowledge_store.get_entry(before.id, project_name="demo")) is None
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].source_report == retained
    assert current[0].source_report.same_account_source(report)
    assert current[0].source_report.period == report.period
    assert TEMPORARY not in current[0].statement
    assert "not independently established" in current[0].statement
    found = _run(search_current_knowledge(backend, project_name="demo", query="Alpha cache local", limit=10))
    assert [row.id for row in found] == [current[0].id]
    assert result.resolution_status == "resolved"
    assert any(item.result.get("truth_change") in {"refine", "replace"} for item in result.items)
    assert set(provider.scopes) == {"maintenance:fixture-original:fixture-generation"}
    account = read_task_budget_receipt(backend.data_dir, provider.scopes[0])
    assert len(account["calls"]) == 4
    assert all(call["phase"] == "dream" and call["usage_exact"] for call in account["calls"])
    assert result.continuation["verification_contract"] == DREAM_SOURCE_RECHECK_CONTRACT == "dream-source-recheck-v16"
    notes = "\n".join(result.notes)
    assert REPORT not in notes
    assert sum(n.startswith("dream verification receipt: ") for n in result.notes) == 4


@pytest.mark.parametrize("failure,proposals,finals", [
    ("rendered_partial", 2, 0), ("original_partial", 2, 0),
    ("defer", 1, 0), ("final_partial", 2, 2), ("drops_meaning", 2, 2),
    ("drop_qualifier", 2, 0),
])
def test_unsupported_or_unrepaired_report_keeps_original_without_refresh_delete_or_unbounded_repair(
    report_case, failure, proposals, finals,
):
    backend, _root, _report, before, _output_item, _retained = report_case
    provider = RenderedProvider(report_case, failure=failure)
    result = invoke(report_case, provider)
    after = _run(backend.structured_store.knowledge_store.get_entry(before.id, project_name="demo"))
    assert after.to_dict() == before.to_dict()
    assert provider.phases.count("proposal") == proposals
    assert provider.phases.count("final") == finals
    assert provider.phases.count("rendered") == (0 if failure == "original_partial" else 1)
    assert result.resolution_status == "unresolved"
    assert not any(item.result.get("truth_change") in {"verification_refreshed", "delete", "refine", "replace"}
                   for item in result.items)
    repairs = [m for m in provider.manifests if m.get("proposal_repair")]
    assert len(repairs) <= 1
    assert all(m["proposal_repair"]["attempt"] == 1 for m in repairs)
    assert len(set(provider.scopes)) == 1


def test_correct_rendered_confirmation_is_not_proposed_or_confirmed_again(report_case):
    provider = RenderedProvider(report_case, failure="confirmation_ok")
    result = invoke(report_case, provider)
    assert provider.phases == ["source", "rendered"]
    assert any(item.result.get("truth_change") == "verification_refreshed" for item in result.items)


def test_direct_original_group_callsite_also_confirms_before_proposing(report_case):
    backend, root, _report, before, _output_item, retained = report_case
    provider = RenderedProvider(report_case)
    # This lower-level call is isolated from the production scheduler; use a
    # fixture-only common task binding, never a live host transport.
    from harness_mem.autonomous.executors.task_budget import bind_maintenance_task
    provider.bind_task_budget(bind_maintenance_task(data_dir=backend.data_dir, host_client="codex",
        config=MergedConfig(), trigger_id="fixture-direct", dispatch_generation="fixture-generation"),
        phase="dream", slice_id="dream:fixture-direct:1")
    items = _run(_run_source_backed_recheck_group(backend, project_name="demo", project_root=root,
        entries=[before], signal=DreamRecheckSignal(kind="stale", target_ids=(before.id,),
            proposed_action="replace", risk="medium", reason="Recheck the complete source report."),
        run_id="fixture-direct", provider=provider, allow_retire=True))
    assert provider.phases == ["source", "rendered", "proposal", "final"]
    assert any(item.result.get("truth_change") in {"refine", "replace"} for item in items)
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.source_report for row in current] == [retained]


def test_original_source_mismatch_stays_unresolved_without_dispatch(report_case, monkeypatch):
    backend, _root, _report, before, _output_item, _retained = report_case
    monkeypatch.setattr(backend.transcript_store, "reconstruct_raw", lambda *_a, **_k: b"changed")
    provider = RenderedProvider(report_case)
    result = invoke(report_case, provider)
    assert provider.phases == []
    after = _run(backend.structured_store.knowledge_store.get_entry(before.id, project_name="demo"))
    assert after.to_dict() == before.to_dict()
    assert result.resolution_status == "unresolved"


def test_ordinary_proposal_call_sequence_is_unchanged(backend):
    entry = KnowledgeEntry(id="ordinary-rendered-control", project_name="demo", title="Cache rule",
        statement=OLD, module_path=["cache"])
    root, _path, _rows = _publish(backend, entry)
    provider = ProposalProvider()
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert provider.phases == ["verify", "assimilate", "verify"]
    assert result.resolution_status == "resolved"
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.statement for row in rows] == [NEW]
