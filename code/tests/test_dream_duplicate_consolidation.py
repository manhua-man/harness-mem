"""Runtime duplicate merge objectives retain one complete source-backed decision."""
from __future__ import annotations

import copy

import pytest

from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
from harness_mem.autonomous.provider import _build_assimilation_prompt, _build_verification_prompt
from harness_mem.commands.dream import dream_once, _normalize_dream_proposal_groups
from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.read_knowledge import search_current_knowledge
from test_dream_stage4_contract import backend as backend, _publish, _result, _run
from test_dream_proposal_group_isolation import prepared, proposal


POLICY = ("Cache admission retains durable reusable rules and excludes greetings, progress and unfinished attempts. "
          "A one-time installation permission is not standing authorization.")


def item(subject="Cache"):
    return dict(title=subject + " complete admission policy", statement=subject + " policy: " + POLICY.replace("Cache", subject),
                topic_path=[subject.lower()], claim_kind="design_requirement")


class MergeProvider:
    name = "isolated-duplicate-merge"

    def __init__(self, *, shape="merge", repair="merge", failure=None, remove_goal=False, after_final=None):
        self.shape, self.repair, self.failure = shape, repair, failure
        self.remove_goal, self.after_final = remove_goal, after_final
        self.proposals, self.finals = [], []

    def assimilate(self, manifest, **_kwargs):
        self.proposals.append(copy.deepcopy(manifest))
        groups = copy.deepcopy(manifest["duplicate_consolidation_groups"])
        assert groups
        # A provider can only see a projection. Removing it does not revoke the
        # runtime operation passed separately to the common Dream normalizer.
        if self.remove_goal:
            manifest.pop("duplicate_consolidation_groups")
        truth = {row["id"]: row for row in manifest["current_truth"]}
        points = []
        for candidate in manifest["verified_candidates"]:
            identity = next(row["target_snapshot"]["id"] for row in manifest["maintenance_candidates"]
                            if row["candidate_id"] == candidate["candidate_id"])
            group = next(group for group in groups if identity in group)
            subject = truth[identity]["statement"].split()[0]
            shape = self.repair if manifest.get("proposal_repair") else self.shape
            if subject == "Queue":
                shape = "merge"  # Independent accepted group is never retried.
            if identity != sorted(group)[0] or shape == "defer":
                points.append(dict(candidate_id=candidate["candidate_id"], disposition="defer" if shape == "defer" else "no_write",
                    matched_truth_handles=[], reason="Do not independently rewrite another member or combine unrelated topics."))
                continue
            outputs = [item(subject)]
            if shape == "fragments":
                outputs = [dict(title=subject + " " + title, statement=subject + " " + text,
                    topic_path=[subject.lower()], claim_kind="design_requirement") for title, text in [
                    ("admission", "admission retains durable reusable rules."),
                    ("exclusions", "admission excludes greetings, progress and unfinished attempts."),
                    ("permission", "one-time installation permission is not standing authorization.")]]
            handles = [truth[member]["handle"] for member in group]
            if shape == "partial_group":
                handles = [truth[identity]["handle"]]
            points.append(dict(candidate_id=candidate["candidate_id"], disposition="replace",
                matched_truth_handles=handles, knowledge_items=outputs,
                reason="Keep one complete coherent admission decision including every exclusion and permission example."))
        return _result(AssimilationDecision.model_validate({"points": points}))

    def verify(self, manifest, **_kwargs):
        final = manifest["contract_version"] == "final-knowledge-scope-v1"
        if final:
            self.finals.append(copy.deepcopy(manifest))
        points = []
        for row in manifest["candidates"]:
            point = dict(candidate_index=row["candidate_index"], semantic_support="supported",
                future_scope="durable", source_use="reusable_knowledge",
                reason="Independently judge the complete source, coherent decision and all exclusion conditions.",
                scope_segments=[dict(text=row["scope_text"], source_use="reusable_knowledge", future_scope="durable",
                    content_role="claim", standalone=True, source_support="supported")])
            if final:
                context = row["update_context"]
                assert context["maintenance_operation"]["kind"] == "duplicate_consolidation"
                assert len(context["predecessors"]) >= 2 and len(context["successors"]) == 1
                assert all(source["content"] for source in row["sources"])
                point["update_meaning_judgment"] = dict(
                    relationship="drops_applicable_meaning" if self.failure == "drops" else "preserves_applicable_meaning",
                    predecessor_conditions=[], predecessor_statements=[old["statement"] for old in context["predecessors"]],
                    predecessor_versions=[old["version"] for old in context["predecessors"]],
                    successor_statements=[new["statement"] for new in context["successors"]],
                    basis="One unified policy retains the complete rule, exclusions and same-scope authorization example.")
                if self.failure == "unsupported":
                    point["semantic_support"] = "partial"
                    point["scope_segments"][0]["source_support"] = "unsupported"
                if self.failure == "missing_meaning":
                    point.pop("update_meaning_judgment")
            points.append(point)
        if final and self.after_final:
            self.after_final()
        return _result(CandidateVerificationDecision.model_validate({"points": points}))


def publish_pair(backend, *, neighbor=False, unrelated=False, member_count=2):
    entries = [KnowledgeEntry(id=identity, project_name="demo", title="Admission " + identity,
        statement=POLICY if not unrelated or identity == "cache-a" else "Battery charging preserves the thermal safety limit.",
        module_path=["cache"]) for identity in ("cache-a", "cache-b", "cache-c")[:member_count]]
    if neighbor:
        entries += [KnowledgeEntry(id=identity, project_name="demo", title="Queue " + identity,
            statement=POLICY.replace("Cache", "Queue"), module_path=["queue"]) for identity in ("queue-a", "queue-b")]
    root, path, _ = _publish(backend, *entries)
    return root, path, entries


def explicit_scope(entries):
    return {"groups": [{"kind": "duplicate", "target_ids": [entry.id for entry in entries]}]}


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("member_count", [2, 3])
def test_duplicate_default_and_explicit_execute_full_final_then_one_canonical_decision(backend, explicit, member_count):
    root, path, entries = publish_pair(backend, member_count=member_count)
    complete_source = path.read_bytes().decode("utf-8")
    provider = MergeProvider()
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider,
        **({"repair_scope": explicit_scope(entries)} if explicit else {})))
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].statement == item()["statement"], (result.notes, result.items)
    assert result.resolution_status == "resolved"
    assert len(provider.proposals) == len(provider.finals) == 1
    assert provider.proposals[0]["duplicate_consolidation_groups"] == [[entry.id for entry in entries]]
    assert all(_run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")) is None for entry in entries)
    assert provider.finals[0]["candidates"][0]["sources"][0]["content"] == complete_source
    assert item()["statement"] in backend.structured_store._canonical.get_payload_json("knowledge_entries", current[0].id)
    found = _run(search_current_knowledge(backend, project_name="demo", query="Cache admission permission", limit=10))
    assert current[0].id in {entry.id for entry in found}


def test_explicit_three_policy_fragments_merge_as_one_decision_with_exclusions(backend):
    fragments = ["Cache admission retains durable reusable rules.",
                 "Cache admission excludes greetings, progress and unfinished attempts.",
                 "Cache one-time installation permission is not standing authorization."]
    entries = [KnowledgeEntry(id=identity, project_name="demo", title="Cache " + identity,
        statement=text, module_path=["cache"]) for identity, text in zip(
            ("cache-a", "cache-b", "cache-c"), fragments)]
    root, _path, _ = _publish(backend, *entries)
    provider = MergeProvider()
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider,
        repair_scope=explicit_scope(entries)))
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].statement == item()["statement"]
    assert result.resolution_status == "resolved"
    assert len(provider.finals[0]["candidates"][0]["update_context"]["predecessors"]) == 3


@pytest.mark.parametrize("shape", ["fragments", "partial_group"])
@pytest.mark.parametrize("repair", ["merge", "fragments", "defer"])
@pytest.mark.parametrize("explicit", [False, True])
def test_structural_rejection_gets_one_bounded_complete_group_correction(backend, shape, repair, explicit):
    root, _path, entries = publish_pair(backend)
    provider = MergeProvider(shape=shape, repair=repair)
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider,
        **({"repair_scope": explicit_scope(entries)} if explicit else {})))
    assert len(provider.proposals) == 2
    fixed = provider.proposals[1]
    assert fixed["duplicate_consolidation_groups"] == [["cache-a", "cache-b"]]
    assert fixed["proposal_repair"]["attempt"] == 1
    assert set(fixed["proposal_repair"]["allowed_target_ids"]) == {entry.id for entry in entries}
    assert fixed["proposal_repair"]["previous_rejections"][0]["reason_code"] == "duplicate_consolidation_incomplete"
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    if repair == "merge":
        assert len(current) == 1 and current[0].statement == item()["statement"]
        assert result.resolution_status == "resolved"
    else:
        assert {entry.id for entry in current} == {entry.id for entry in entries}
        assert result.resolution_status == "unresolved"
    assert len(provider.finals) == int(repair == "merge")


def test_provider_removing_manifest_goal_cannot_turn_merge_into_fragments(backend):
    root, _path, entries = publish_pair(backend)
    provider = MergeProvider(shape="fragments", repair="fragments", remove_goal=True)
    _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert len(provider.proposals) == 2 and provider.finals == []
    assert {entry.id for entry in _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))} == {entry.id for entry in entries}


@pytest.mark.parametrize("failure", ["unsupported", "drops", "missing_meaning"])
def test_merge_objective_does_not_replace_independent_final_source_and_meaning(backend, failure):
    root, _path, entries = publish_pair(backend)
    provider = MergeProvider(failure=failure)
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert result.resolution_status == "unresolved"
    assert {entry.id for entry in _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))} == {entry.id for entry in entries}
    assert len(provider.proposals) == len(provider.finals) == 2


def test_genuinely_independent_topics_can_abstain_without_fallback_write(backend):
    root, _path, entries = publish_pair(backend, unrelated=True)
    provider = MergeProvider(shape="defer")
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider,
        repair_scope=explicit_scope(entries)))
    assert provider.finals == []
    assert {entry.id for entry in _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))} == {entry.id for entry in entries}
    assert result.resolution_status == "unresolved"


def test_repair_preserves_independent_already_accepted_merge_component(backend):
    root, _path, entries = publish_pair(backend, neighbor=True)
    provider = MergeProvider(shape="fragments")
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert len(provider.proposals) == 2
    assert {row["candidate_id"] for row in provider.proposals[1]["verified_candidates"]} == {"dream:cache-a"}
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert {entry.statement for entry in current} == {item()["statement"], item("Queue")["statement"]}
    assert len(current) == 2 and result.resolution_status == "resolved"
    assert len(provider.finals) == 2
    assert {entry.id for entry in current}.isdisjoint(entry.id for entry in entries)


def test_final_source_change_keeps_original_complete_group(backend):
    root, path, entries = publish_pair(backend)
    provider = MergeProvider(after_final=lambda: path.write_text("Changed source after independent verification.", encoding="utf-8"))
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert {entry.id for entry in current} == {entry.id for entry in entries}
    assert result.resolution_status == "unresolved"


def test_member_disappearing_after_final_cannot_apply_partial_group(backend, monkeypatch):
    root, _path, entries = publish_pair(backend)
    store = backend.structured_store.knowledge_store
    original_get = store.get_entry

    def hide_member():
        async def changed_get(identity, **kwargs):
            if identity == "cache-b":
                return None
            return await original_get(identity, **kwargs)
        monkeypatch.setattr(store, "get_entry", changed_get)

    provider = MergeProvider(after_final=hide_member)
    result = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert len(provider.finals) == 1
    # Inspect actual canonical rows through the original reader after the
    # disappearing-member race was presented to the maintenance consumer.
    assert all(_run(original_get(entry.id, project_name="demo")) == entry for entry in entries)
    assert result.resolution_status == "unresolved"


@pytest.mark.parametrize("fault", ["incomplete", "cross_group", "changed_runtime_group"])
def test_group_shape_cannot_change_original_runtime_membership(fault):
    source = prepared()
    decision = proposal()
    decision.points[1].disposition = "no_write"
    decision.points[1].matched_truth_handles = []
    decision.points[1].knowledge_items = []
    decision.points[0].matched_truth_handles = ["K0", "K1"]
    groups = [["entry-0", "entry-1"], ["entry-2"]]
    consolidation = [["entry-0", "entry-1"]]
    if fault == "incomplete":
        decision.points[0].matched_truth_handles = ["K0"]
    elif fault == "cross_group":
        decision.points[0].matched_truth_handles.append("K2")
    else:
        consolidation = [["entry-0", "entry-2"]]
    payloads = _normalize_dream_proposal_groups(source, decision,
        identities={f"entry-{i}": f"dream:entry-{i}" for i in range(3)}, groups=groups,
        report_ids=set(), receipts=[], consolidation_groups=consolidation)
    assert all(point["candidate_id"] != "dream:entry-0" for point, _payload in payloads)


@pytest.mark.parametrize("fault", ["two_writers", "nonempty_abstention", "confirmation"])
def test_group_has_only_one_full_writer_and_empty_handle_abstentions(fault):
    source = prepared(2)
    decision = proposal(2)
    decision.points[0].matched_truth_handles = ["K0", "K1"]
    if fault == "two_writers":
        decision.points[1].matched_truth_handles = ["K0", "K1"]
    else:
        decision.points[1].disposition = "no_write" if fault == "nonempty_abstention" else "confirm"
        decision.points[1].knowledge_items = []
    payloads = _normalize_dream_proposal_groups(source, decision,
        identities={f"entry-{i}": f"dream:entry-{i}" for i in range(2)},
        groups=[["entry-0", "entry-1"]], consolidation_groups=[["entry-0", "entry-1"]],
        report_ids=set(), receipts=[])
    assert payloads == []


def test_plain_refinement_multi_output_and_untrusted_manifest_claim_remain_compatible():
    source = prepared(1)
    source.manifest["duplicate_consolidation_groups"] = [["entry-0", "unknown"]]
    decision = proposal(1)
    decision.points[0].knowledge_items.append(decision.points[0].knowledge_items[0].model_copy(update={
        "title": "Cache alternative", "statement": "Cache independently remains signed."}))
    payloads = _normalize_dream_proposal_groups(source, decision,
        identities={"entry-0": "dream:entry-0"}, groups=[["entry-0"]], report_ids=set(), receipts=[])
    assert len(payloads) == 1 and len(payloads[0][1]["knowledge_items"]) == 2


def test_prompts_make_coherence_and_runtime_scope_explicit():
    ordinary = _build_assimilation_prompt({"verified_candidates": []})
    assert len(ordinary) < 5500
    assert "except an explicit runtime" not in ordinary
    manifest = dict(verified_candidates=[], current_truth=[], maintenance_candidates=[{}],
        duplicate_consolidation_groups=[["a", "b"]])
    text = _build_assimilation_prompt(manifest)
    assert "conditions, exclusions and qualifying examples" in text
    assert "exactly one complete" in text
    for native in (False, True):
        text = _build_verification_prompt(dict(contract_version="final-knowledge-scope-v1", candidates=[]),
                                          native_final_transport=native)
        assert "one coherent decision" in text
        assert "artificial conjunction of independent topics" in text
