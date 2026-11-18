"""Complete current offers reuse bounded pages and never assert semantic absence."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from harness_mem.commands import separated_assimilation as owner
from harness_mem.core.schemas import EvidenceRef, KnowledgeCandidate, KnowledgeEntry, KnowledgeEvidence
from harness_mem.core.schemas.source_report import SourceReport
from test_dream_stage4_contract import backend as backend, _publish, _run


class Store:
    def __init__(self, count=102, mutate=None):
        self.entries = [KnowledgeEntry(id=f"current-{index:04}", project_name="demo",
            title="Cache policy", statement=f"Cache policy {index} remains scoped.",
            module_path=["cache"]) for index in range(count)]
        self.calls = 0
        self.mutate = mutate

    async def list_entries(self, *_args, **_kwargs):
        self.calls += 1
        if self.mutate:
            self.mutate(self)
        return [entry.model_copy(deep=True) for entry in reversed(self.entries)]


def environment(count=102, mutate=None):
    store = Store(count, mutate)
    return SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store)), store


def candidate(statement="Cache policy remains scoped.", report=None):
    return KnowledgeCandidate(id="candidate", project_name="demo", candidate_type="memory",
                              statement=statement, source_report=report)


def complete(backend, *, candidates=None, required=()):
    discovery = {}
    handles, rows = asyncio.run(owner._complete_current_truth_handles(backend, project_name="demo",
        project_root="isolated-project", candidates=candidates or [candidate()],
        required_target_ids=required, discovery=discovery))
    return handles, rows, discovery


@pytest.mark.parametrize("count", [0, 1, 32, 33, 102, 129, 257])
def test_complete_offer_walks_every_bounded_page_and_mints_unique_ranked_handles(count):
    backend, store = environment(count)
    handles, rows, discovery = complete(backend)
    assert len(handles) == len(rows) == count
    assert list(handles) == [f"T{index}" for index in range(1, count + 1)]
    assert len(set(handles.values())) == count
    assert discovery["current_count"] == discovery["offered_count"] == count
    assert discovery["status"] == "complete" and discovery["next_offset"] is None
    assert discovery["absence_proved"] is False
    assert discovery["page_count"] == store.calls == max(1, (count + 31) // 32)


def test_required_targets_are_deduplicated_without_promoting_their_rank():
    backend, _store = environment(150)
    handles, rows, discovery = complete(backend, required=["current-0149", "current-0149", "current-0001"])
    assert list(handles.values()) == [f"current-{index:04}" for index in range(150)]
    assert len(rows) == discovery["offered_count"] == 150
    assert discovery["required_target_count"] == 2


def test_report_account_priority_survives_complete_pagination_and_required_union():
    backend, store = environment(140)
    report = SourceReport(speaker="assistant", period="2026-10-21T00:00:00Z", session_id="same-session",
        source_id="same-source", source_revision="same-revision", exchange_indexes=[1], text="A scoped account.")
    for entry in store.entries[-3:]:
        entry.source_report = report.model_copy(update={"text": entry.statement})
    handles, _rows, discovery = complete(backend, candidates=[candidate(report.text, report)], required=["current-0139"])
    assert list(handles.values())[:3] == ["current-0137", "current-0138", "current-0139"]
    assert discovery["related_account_count"] == 3 and len(handles) == 140


@pytest.mark.parametrize("fault", ["count", "same_count_body", "same_count_title", "same_count_topic", "same_count_identity", "same_count_authority"])
def test_page_two_reopens_all_current_semantics_and_rejects_drift(fault):
    def mutate(store):
        if store.calls != 2:
            return
        if fault == "count":
            store.entries.pop()
        elif fault == "same_count_body":
            store.entries[-1].statement = "A different scoped obligation."
        elif fault == "same_count_title":
            store.entries[-1].title = "Changed title"
        elif fault == "same_count_topic":
            store.entries[-1].module_path = ["other-scope"]
        elif fault == "same_count_identity":
            store.entries[-1].id = "replacement-identity"
        else:
            store.entries[-1].source_report = SourceReport(speaker="assistant", period="unknown",
                session_id="another", source_id="another", source_revision="changed", exchange_indexes=[1],
                text=store.entries[-1].statement)
    backend, store = environment(mutate=mutate)
    with pytest.raises(ValueError, match="current_set_changed"):
        complete(backend)
    assert store.calls == 2


def test_access_and_verification_metadata_do_not_change_semantic_inventory():
    def mutate(store):
        for entry in store.entries:
            entry.verified_at = datetime.now(timezone.utc)
            entry.updated_at = datetime.now(timezone.utc)
    backend, _store = environment(mutate=mutate)
    assert len(complete(backend)[0]) == 102


@pytest.mark.parametrize("fault", ["missing", "repeat", "nonadvancing", "skip", "early_terminal", "foreign", "false_count", "same_count_row_drift"])
def test_incomplete_repeated_foreign_or_malformed_pages_cannot_claim_complete(monkeypatch, fault):
    backend, _store = environment()
    original = owner._current_truth_handles

    async def broken(*args, **kwargs):
        handles, rows = await original(*args, **kwargs)
        if kwargs["offset"] != 32:
            return handles, rows
        page = kwargs["discovery"]
        if fault == "missing":
            rows.pop()
        elif fault == "repeat":
            again = {**kwargs, "offset": 0}
            handles, rows = await original(*args, **again)
            page.update(offset=32, next_offset=64)
        elif fault == "nonadvancing":
            page["next_offset"] = 32
        elif fault == "skip":
            page["next_offset"] = 96
        elif fault == "early_terminal":
            page["next_offset"] = None
        elif fault == "foreign":
            before = handles[rows[0]["handle"]]
            handles[rows[0]["handle"]] = "foreign-project-entry"
            page["_ranked_page_ids"] = ["foreign-project-entry" if identity == before else identity
                                        for identity in page["_ranked_page_ids"]]
        elif fault == "false_count":
            page["current_count"] = len(rows)
        else:
            rows[0]["statement"] = "Different body despite a copied full-set fingerprint."
        return handles, rows

    monkeypatch.setattr(owner, "_current_truth_handles", broken)
    with pytest.raises(ValueError, match="complete_target_discovery_"):
        complete(backend)


def test_foreign_canonical_inventory_and_missing_required_target_fail_closed():
    backend, store = environment()
    store.entries[-1].project_name = "another-project"
    with pytest.raises(ValueError, match="project_mismatch"):
        complete(backend)
    backend, _store = environment()
    with pytest.raises(ValueError, match="inventory_incomplete"):
        complete(backend, required=["missing-target"])


@pytest.mark.parametrize("complete_mode", [False, True])
def test_real_preparation_opt_in_keeps_default32_and_exposes_full_gt128_without_absence(backend, complete_mode):
    entries = [KnowledgeEntry(id=f"current-{index:04}", project_name="demo", title="Cache policy",
        statement=f"Cache policy {index} remains scoped.", module_path=["cache"]) for index in range(145)]
    root, source, _entries = _publish(backend, *entries)
    value = candidate()
    store = backend.structured_store.knowledge_store
    _run(store.save_candidate(value))
    _run(store.save_evidence(KnowledgeEvidence(project_name="demo", candidate_id=value.id,
        distill_job_id="isolated-target-source", evidence_basis="repository", verification_outcome="verified",
        verification_refs=[EvidenceRef(kind="repository", locator=source.name,
            content_sha256=hashlib.sha256(source.read_bytes()).hexdigest())],
        verification_reason_codes=["semantic_support_verified", "future_utility_verified"])))
    prepared = _run(owner.prepare_separated_assimilation(backend, project_name="demo", project_root=str(root),
        candidate_ids=[value.id], complete_target_discovery=complete_mode))
    assert prepared.eligible_candidate_ids == (value.id,)
    count = 145 if complete_mode else 32
    discovery = prepared.manifest["truth_target_discovery"]
    assert len(prepared.truth_by_handle) == len(prepared.manifest["current_truth"]) == discovery["offered_count"] == count
    assert discovery["current_count"] == 145
    assert discovery["status"] == ("complete" if complete_mode else "incomplete")
    assert discovery["absence_proved"] is False
    assert discovery["current_set_sha256"] == prepared.manifest["truth_target_expansion"]["current_set_sha256"]
    assert "_ranked_page_ids" not in prepared.manifest["truth_target_expansion"]


def test_full_offer_with_no_lexical_match_still_never_proves_absence():
    backend, _store = environment(65)
    unrelated = candidate("Zygomorphic orchid cultivar registration.")
    _handles, rows, discovery = complete(backend, candidates=[unrelated])
    assert discovery["absence_proved"] is False
    assert owner._unmatched_candidate_ids([unrelated], rows) == [unrelated.id]
