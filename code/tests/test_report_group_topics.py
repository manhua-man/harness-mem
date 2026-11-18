"""Every report in a consolidation retains its own exact topic authority."""
import asyncio
import copy
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
from harness_mem.commands.knowledge_assimilation import (
    _bind_report_topic_relations, assimilation_decision_id,
)
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation, _interactive_proposal, _validate_apply_points,
    bind_final_scope_judgment, final_scope_payload, final_scope_proof,
    final_scope_verification_rows, target_version, validate_separated_assimilation_decision,
)
from harness_mem.core.schemas.knowledge import AssimilationDecision as StoredDecision
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import (
    ReportTopicJudgment, SourceReport, bind_report_preservation_inventory,
    bind_report_preservation_inventories,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def case():
    from test_report_multi_predecessor_preservation import endpoints, segment

    targets, items, _originals = endpoints()
    title = "Local cache and archive validation limits"
    targets[1]["source_report"]["topic_title"] = title
    second = SourceReport.model_validate(targets[1]["source_report"])
    targets[1].update(title=second.render_title(), statement=second.render_statement())
    for target in targets:
        target["topic_path"] = ["Reports"]
        target["version"] = target_version(target)
    final = SourceReport.model_validate(items[0]["source_report"]).model_copy(update={"topic_title": title})
    items[0].update(title=title, statement=final.render_statement(), source_report=final.model_dump(mode="json"),
                    topic_path=["Reports"], claim_kind="source_report")
    candidate_report = final.model_copy(update={"topic_title": None})
    judgments = [{"relationship": "same_topic", "predecessor_title": target["title"],
        "successor_title": title, "basis": "Each complete original concerns this local cache and archive validation boundary."}
        for target in targets]
    prepared = SeparatedPreparedAssimilation(project_name="demo", project_root="/demo",
        candidate_ids=("candidate",), eligible_candidate_ids=("candidate",), automatic_points=(),
        answer_status_by_candidate={"candidate": "ANSWERED"}, truth_by_handle={"T1": "old-0", "T2": "old-1"},
        manifest={"verified_candidates": [{"candidate_id": "candidate", "kind": "memory",
            "statement": candidate_report.text, "semantic_support": "supported",
            "source_report": candidate_report.model_dump(mode="json")}],
            "current_truth": [{"handle": f"T{index + 1}", **target} for index, target in enumerate(targets)]})
    decision = {"points": [{"candidate_id": "candidate", "disposition": "replace",
        "matched_truth_handles": ["T1", "T2"], "knowledge_items": [{key: value for key, value in items[0].items()
            if key != "source_report"}], "report_topic_judgments": judgments,
        "reason": "Retain both complete reports and every explicit remaining verification limit."}]}
    inventories = []
    for target in targets:
        report = SourceReport.model_validate(target["source_report"])
        classification = {"scope_segments": [segment(report.text)], "claim_units": [{"first_segment": 0,
            "end_segment_exclusive": 1, "standalone": True, "source_support": "supported",
            "source_use": "reusable_knowledge", "future_scope": "durable"}]}
        inventories.append(bind_report_preservation_inventory(owner="candidate", target=target,
            items=items, omissions=[], classification=classification, mode="full_revision"))
    inventory = bind_report_preservation_inventories(owner="candidate", targets=targets, items=items,
        inventories=inventories, expected_mode="full_revision")
    return prepared, decision, targets, items, candidate_report, inventory


def test_legacy_and_named_predecessors_each_keep_their_exact_ordered_topic_vote():
    prepared, raw, _targets, _items, report, inventory = case()
    plan = validate_separated_assimilation_decision(prepared, AssimilationDecision.model_validate(raw))
    point = plan["points"][0]
    assert point["report_topic_judgments"] == raw["points"][0]["report_topic_judgments"]
    assert point["knowledge_items"][0]["statement"] == report.render_statement()
    point["report_preservation_inventory"] = inventory
    payload = final_scope_payload(prepared, point)
    assert payload["report_topic_judgments"] == point["report_topic_judgments"]
    reapplied = _validate_apply_points(prepared, [point])[0]
    assert reapplied["report_topic_judgments"] == point["report_topic_judgments"]
    changed = copy.deepcopy(payload)
    changed["report_topic_judgments"][1]["basis"] = "A changed semantic relationship is a new exact final payload."
    assert final_scope_proof(changed) != final_scope_proof(payload)


@pytest.mark.parametrize("fault", ["missing", "partial", "swapped", "duplicate", "negative",
    "unclear", "foreign_title", "foreign_successor", "mixed_formats", "foreign_account"])
def test_missing_borrowed_or_conflicting_topic_votes_cannot_authorize_a_group(fault):
    prepared, raw, _targets, _items, _report, _inventory = case()
    point = raw["points"][0]
    topics = point["report_topic_judgments"]
    if fault == "missing":
        point.pop("report_topic_judgments")
    elif fault == "partial":
        topics.pop()
    elif fault == "swapped":
        topics.reverse()
    elif fault == "duplicate":
        topics[1] = copy.deepcopy(topics[0])
    elif fault in {"negative", "unclear"}:
        topics[1]["relationship"] = "unrelated" if fault == "negative" else "unclear"
    elif fault == "foreign_title":
        topics[1]["predecessor_title"] = "Unrelated report"
    elif fault == "foreign_successor":
        topics[1]["successor_title"] = "Another output"
    elif fault == "mixed_formats":
        point["report_topic_judgment"] = topics[0]
    else:
        prepared.manifest["current_truth"][1]["source_report"]["session_id"] = "foreign-session"
    with pytest.raises(ValueError):
        validate_separated_assimilation_decision(prepared, AssimilationDecision.model_validate(raw))


def test_identical_generic_titles_still_need_one_vote_per_bound_predecessor():
    _prepared, raw, targets, items, report, _inventory = case()
    predecessors = [SourceReport.model_validate(row["source_report"]).model_copy(update={"topic_title": None})
                    for row in targets]
    topic = ReportTopicJudgment.model_validate(raw["points"][0]["report_topic_judgments"][0])
    assert _bind_report_topic_relations(report, predecessors, disposition="replace",
        proposed_title=items[0]["title"], judgments=[topic, topic]).render_title() == items[0]["title"]
    with pytest.raises(ValueError, match="every predecessor"):
        _bind_report_topic_relations(report, predecessors, disposition="replace",
            proposed_title=items[0]["title"], judgments=[topic])


def test_same_title_and_body_cannot_hide_a_negative_explicit_group_vote():
    _prepared, raw, targets, _items, _report, _inventory = case()
    before = SourceReport.model_validate(targets[0]["source_report"])
    vote = ReportTopicJudgment(relationship="unrelated", predecessor_title=before.render_title(),
        successor_title=before.render_title(), basis="An explicit negative relation cannot be ignored on identical bytes.")
    with pytest.raises(ValueError, match="topic judgment"):
        _bind_report_topic_relations(before, [before, before], disposition="replace", judgments=[vote, vote])


def test_interactive_proposal_relays_current_agent_judgments_without_creating_them():
    prepared, raw, targets, _items, report, _inventory = case()
    candidate = KnowledgeCandidate(id="candidate", project_name="demo", candidate_type="memory",
        statement=report.text, source_report=report, assimilation_disposition="replace",
        assimilation_reason=raw["points"][0]["reason"], assimilation_target_ids=[row["id"] for row in targets],
        canonical_title=raw["points"][0]["knowledge_items"][0]["title"], topic_path=["Reports"])
    store = SimpleNamespace(list_entries=AsyncMock(return_value=[KnowledgeEntry(id=row["id"],
        project_name="demo", title=row["title"], statement=row["statement"], module_path=row["topic_path"],
        source_report=SourceReport.model_validate(row["source_report"])) for row in targets]),
        list_evidence=AsyncMock(return_value=[]))
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store))
    topics = raw["points"][0]["report_topic_judgments"]
    result = asyncio.run(_interactive_proposal(backend, prepared, candidate, topic_judgments=topics))
    assert result["report_topic_judgments"] == topics
    assert result["matched_truth_handles"] == ["T1", "T2"]
    without = asyncio.run(_interactive_proposal(backend, prepared, candidate))
    assert "report_topic_judgments" not in without


def test_final_vote_must_bind_the_same_complete_topic_list_and_native_transport_retains_it():
    from harness_mem.autonomous.models import NativeFinalScopeDecision
    from test_report_original_inventory import native_vote

    prepared, raw, _targets, _items, _report, inventory = case()
    point = validate_separated_assimilation_decision(prepared, AssimilationDecision.model_validate(raw))["points"][0]
    point["report_preservation_inventory"] = inventory
    payload = final_scope_payload(prepared, point)
    rows = final_scope_verification_rows(payload, [{"kind": "session", "role": "assistant",
        "content": prepared.manifest["verified_candidates"][0]["source_report"]["text"]}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    response = native_vote(manifest)
    for vote in response["points"]:
        vote["report_topic_judgments"] = point["report_topic_judgments"]
    verified = NativeFinalScopeDecision.model_validate(response).as_verification(manifest)
    assert bind_final_scope_judgment(rows, verified) == {}
    response["points"][0]["report_topic_judgments"] = response["points"][0]["report_topic_judgments"][:1]
    assert bind_final_scope_judgment(rows, NativeFinalScopeDecision.model_validate(response).as_verification(manifest)) == {
        "candidate": "final_report_topic_judgments_changed"}


def test_optional_list_does_not_change_old_serialized_models_or_empty_commit_identity():
    from test_report_account_identity import report_judgment
    _prepared, raw, _targets, _items, report, _inventory = case()
    legacy = report_judgment(report, report.render_title())
    assert "report_topic_judgments" not in legacy["points"][0]
    assert CandidateVerificationDecision.model_validate(legacy).model_dump(mode="json") == legacy
    single = copy.deepcopy(raw)
    topics = single["points"][0].pop("report_topic_judgments")
    single["points"][0]["report_topic_judgment"] = topics[0]
    dumped = AssimilationDecision.model_validate(single).model_dump(mode="json")
    assert dumped["points"][0]["report_topic_judgment"] == topics[0]
    assert "report_topic_judgments" not in dumped["points"][0]
    kwargs = dict(candidate_id="candidate", disposition="replace", knowledge_ids=["new"],
        predecessor_ids=["first", "second"], reason="Keep the complete report meanings.")
    legacy_id = assimilation_decision_id(**kwargs)
    assert assimilation_decision_id(**kwargs, report_topic_judgments=[]) == legacy_id
    bound_id = assimilation_decision_id(**kwargs, report_topic_judgments=topics)
    assert bound_id != legacy_id
    changed = copy.deepcopy(topics)
    changed[1]["relationship"] = "unclear"
    assert assimilation_decision_id(**kwargs, report_topic_judgments=changed) != bound_id
    stored = StoredDecision(project_name="demo", candidate_id="candidate", disposition="replace",
        report_topic_judgments=topics, reason="Keep every explicit topic relation.")
    assert StoredDecision.from_dict(stored.to_dict()).to_dict() == stored.to_dict()
    old = stored.model_copy(update={"report_topic_judgments": []}).to_dict()
    assert "report_topic_judgments" not in old
    assert StoredDecision.from_dict(old).to_dict() == old


@pytest.mark.parametrize("fault", [None, "missing", "partial", "negative", "duplicate", "account", "candidate_body"])
def test_canonical_transaction_rechecks_each_topic_and_binds_receipt_identity(tmp_path, fault):
    prepared, raw, targets, items, report, _inventory = case()
    topics = raw["points"][0]["report_topic_judgments"]
    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        store = backend.structured_store.knowledge_store
        root = tmp_path / "project"
        root.mkdir()
        source = root / "source.jsonl"
        source.write_text(report.text, encoding="utf-8")
        def refs(value):
            return [ProjectKnowledgeSourceRef(label="Bound source", kind="source_report",
                digest=hashlib.sha256(source.read_bytes()).hexdigest(), target=source.as_uri()
                + f"#source_id={value.source_id}&source_revision={value.source_revision}"
                  f"&exchange={index}&role={value.speaker}") for index in value.exchange_indexes]
        try:
            old = []
            for index, target in enumerate(targets):
                original = SourceReport.model_validate(target["source_report"])
                candidate = KnowledgeCandidate(id=f"seed-{index}", project_name="demo", candidate_type="memory",
                    statement=original.text, source_report=original)
                entry = KnowledgeEntry(id=target["id"], project_name="demo", title=original.render_title(),
                    statement=original.render_statement(), source_report=original, module_path=["Reports"])
                decision = StoredDecision(project_name="demo", candidate_id=candidate.id, disposition="add",
                    canonical_truth_ids=[entry.id], reason="Initial isolated current report.")
                await store.apply_current_change(project_root=root, candidate_before=candidate,
                    candidate_after=candidate.model_copy(update={"status": "assimilated"}), decision=decision,
                    added_entries=[entry], predecessor_entries=[], source_refs_by_entry={entry.id: refs(original)})
                old.append(entry)
            actual_topics = copy.deepcopy(topics)
            if fault == "missing":
                actual_topics = []
            elif fault == "partial":
                actual_topics.pop()
            elif fault == "negative":
                actual_topics[1]["relationship"] = "unrelated"
            elif fault == "duplicate":
                actual_topics[1] = copy.deepcopy(actual_topics[0])
            candidate = KnowledgeCandidate(id="candidate", project_name="demo", candidate_type="memory",
                statement=report.text, source_report=report)
            written = SourceReport.model_validate(items[0]["source_report"])
            if fault == "account":
                written = written.model_copy(update={"session_id": "foreign-session"})
            elif fault == "candidate_body":
                candidate.source_report = report.model_copy(update={"text": "A different unverified body."})
            entry = KnowledgeEntry(id="successor", project_name="demo", title=written.render_title(),
                statement=written.render_statement(), source_report=written, module_path=["Reports"])
            identity = assimilation_decision_id(candidate_id=candidate.id, disposition="replace",
                knowledge_ids=[entry.id], predecessor_ids=[row.id for row in old],
                report_topic_judgments=actual_topics, reason="Retain all original report topics.")
            decision = StoredDecision(id=identity, project_name="demo", candidate_id=candidate.id,
                disposition="replace", canonical_truth_ids=[entry.id], predecessor_truth_ids=[row.id for row in old],
                predecessor_entries=old, report_topic_judgments=actual_topics,
                reason="Retain all original report topics.")
            async def apply():
                return await store.apply_current_change(project_root=root, candidate_before=candidate,
                    candidate_after=candidate.model_copy(update={"status": "assimilated"}), decision=decision,
                    added_entries=[entry], predecessor_entries=old, source_refs_by_entry={entry.id: refs(written)})
            if fault:
                with pytest.raises(ValueError):
                    await apply()
                assert {row.id: row.to_dict() for row in await store.list_entries("demo")} == {
                    row.id: row.to_dict() for row in old}
                assert not await store.current_change_committed(identity)
            else:
                await apply()
                assert await store.current_change_committed(identity)
                assert [row.id for row in await store.list_entries("demo")] == [entry.id]
                missing_vote_id = assimilation_decision_id(candidate_id=candidate.id, disposition="replace",
                    knowledge_ids=[entry.id], predecessor_ids=[row.id for row in old],
                    report_topic_judgments=topics[:1], reason="Retain all original report topics.")
                assert not await store.current_change_committed(missing_vote_id)
        finally:
            await backend.close()
    asyncio.run(exercise())
