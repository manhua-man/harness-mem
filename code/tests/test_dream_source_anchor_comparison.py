"""Related user-source claims are hypotheses, not automatic duplicate verdicts."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from harness_mem.commands import dream
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.autonomous.models import CandidateVerificationDecision, CandidateVerificationPoint, CandidateScopeSegment


def run(value):
    return asyncio.run(value)


@pytest.mark.parametrize("fault,expect_group", [(None, True), ("anchor", False), ("source", False), ("role", False), ("project", False), ("already_compared", False), ("other_source_changed", True)])
def test_semantic_paraphrases_share_only_exact_original_user_anchors(tmp_path, monkeypatch, fault, expect_group):
    entries = [KnowledgeEntry(id="old", project_name="demo", title="Retain decisions",
        statement="Preserve explicit decisions.", module_path=["memory"]),
        KnowledgeEntry(id="new", project_name="demo", title="Decisions from new sessions",
        statement="During intake, retain explicit decisions.", module_path=["memory"])]
    async def list_entries(_project):
        return entries
    other_hash = {"digest": "d" * 64}
    async def list_sources(identity):
        changed = identity == "new"
        sources = [NS(source_kind="observation" if changed and fault == "role" else "user_statement",
            project_name="other" if changed and fault == "project" else "demo", knowledge_id=identity,
            content_sha256="c" * 64,
            locator="file:///retained.sqlite#source_id=" + ("other" if changed and fault == "source" else "native-source")
                + "&source_revision=" + ("new" if changed else "old") + "&exchange=78&anchor_sha256="
                + (("b" if changed and fault == "anchor" else "a") * 64))]
        if changed and fault == "other_source_changed":
            sources.append(NS(source_kind="observation", project_name="demo", knowledge_id=identity,
                locator="file:///another-source", content_sha256=other_hash["digest"]))
        return sources
    async def signals(*_args, **_kwargs):
        return []
    async def no_coverage(*_args, **_kwargs):
        return {}
    backend = NS(structured_store=NS(knowledge_store=NS(list_entries=list_entries, list_sources=list_sources),
        query_retrieval_signals=signals))
    monkeypatch.setattr(dream, "_scope_upgrade_coverage", no_coverage)
    monkeypatch.setattr(dream, "_scope_recheck_attempt_times", no_coverage)
    monkeypatch.setattr(dream, "_current_source_reviews", lambda *_: no_coverage_pair())
    async def no_coverage_pair():
        return {}, {}
    result = run(dream._detect_separated_rechecks(backend, project_name="demo", project_root=tmp_path))
    if fault in {"already_compared", "other_source_changed"}:
        previous = next(row for row in result if row.kind == "duplicate")
        async def known_comparison(*_args, **_kwargs):
            return {"old": {"compared_groups": [previous.cause_id]}}
        monkeypatch.setattr(dream, "_scope_upgrade_coverage", known_comparison)
        if fault == "other_source_changed":
            other_hash["digest"] = "e" * 64
        result = run(dream._detect_separated_rechecks(backend, project_name="demo", project_root=tmp_path))
    groups = [row for row in result if row.kind == "duplicate"]
    assert bool(groups) is expect_group
    if groups:
        assert groups[0].target_ids == ("new", "old")
        assert "Compare" in groups[0].reason
    assert entries[0].statement == "Preserve explicit decisions."
    if fault == "already_compared":
        entries[1].statement += " A new condition."
        changed = run(dream._detect_separated_rechecks(backend, project_name="demo", project_root=tmp_path))
        assert any(row.kind == "duplicate" for row in changed)


@pytest.mark.parametrize("grouped,explicit,expect_call", [(False, False, False), (True, False, True), (False, True, True)])
def test_supported_points_still_receive_group_or_explicit_reassessment(tmp_path, monkeypatch, grouped, explicit, expect_call):
    entries = [KnowledgeEntry(id=name, project_name="demo", title=name,
        statement="An independently supported claim.", module_path=["memory"])
        for name in (["one", "two"] if grouped else ["one"])]
    rows = [(entry, NS(evidence_basis="user_statement"), (), ()) for entry in entries]
    checked = {entry.id: CandidateVerificationPoint(candidate_index=index, semantic_support="supported",
        source_use="reusable_knowledge", future_scope="durable", reason="Supported current wording.",
        scope_segments=[CandidateScopeSegment(text=entry.title + "\n" + entry.statement,
            source_support="supported", content_role="claim", source_use="reusable_knowledge",
            future_scope="durable", standalone=True)]) for index, entry in enumerate(entries)}
    calls = []
    class ObservedProposal(Exception):
        pass
    async def call(_backend, **kwargs):
        calls.append(kwargs["manifest"])
        assert kwargs["phase"] == "assimilate"
        raise ObservedProposal
    monkeypatch.setattr(dream, "_run_dream_provider_call", call)
    operation = dream._complete_dream_proposals(NS(data_dir=tmp_path), project_name="demo",
        rechecked=rows, provider=object(), checked=checked,
        comparison_groups=[[entry.id for entry in entries]],
        reassess_ids={entry.id for entry in entries} if explicit else None)
    if expect_call:
        with pytest.raises(ObservedProposal):
            run(operation)
        manifest = calls[0]
        assert manifest["final_scope_required"] is True
        assert "restore" in manifest["maintenance_purpose"]["instruction"]
        assert len(manifest["verified_candidates"]) == len(entries)
    else:
        assert run(operation) == checked and calls == []
    assert CandidateVerificationDecision(points=list(checked.values())).points
