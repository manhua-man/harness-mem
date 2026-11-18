"""Read-only comparison retains exact original source and mutation boundaries."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from harness_mem.adapters.snapshot import _native_codex_authored_texts, persist_session_snapshot
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.commands.dream_assimilation import _entry_version_snapshot
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import KnowledgeEntry, KnowledgeSource
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp.distill_projection import render_distill_exchange_windows


def run(value):
    return asyncio.run(value)


def seed(captured, *, identity="comparison-row", project="demo", sources=None, report=False):
    backend, _root, snapshot, _rendering, originals = captured
    entry = KnowledgeEntry(id=identity, project_name=project, module_path=["another-subject"],
        title="A different lexical subject", statement="An already retained source condition.")
    if report:
        account = SourceReport(speaker="assistant", period="unknown", session_id=snapshot.source.session_id,
            source_id=snapshot.source.id, source_revision=snapshot.source.source_revision,
            exchange_indexes=[1], text="A historical assistant report.")
        entry = entry.model_copy(update={"source_report": account,
            "title": account.render_title(), "statement": account.render_statement()})
    refs = [value.model_copy(update={"id": f"{identity}-source-{index}", "knowledge_id": identity})
            for index, value in enumerate(originals[:1] if sources is None else sources)]
    canonical = backend.structured_store._canonical
    mutations = [{"operation": "upsert", "collection": "knowledge_entries", "entity_id": entry.id,
        "payload": entry.to_dict()}] + [{"operation": "upsert", "collection": "knowledge_sources",
            "entity_id": source.id, "payload": source.to_dict()} for source in refs]
    canonical.apply_payload_transaction(idempotency_key="isolated-comparison:" + identity, mutations=mutations)
    return entry, refs


def compare(captured, *, successors=()):
    backend, root, snapshot, rendering, _sources = captured
    revision = backend.transcript_store.get_revision(snapshot.source.id, snapshot.source.source_revision)
    windows = render_distill_exchange_windows(rendering, range(1, len(owner._parse_exchanges(rendering)[1]) + 1))
    return run(owner._current_source_comparison(backend, project_name="demo", project_root=root,
        original_revision=revision, original_windows=windows, successor_ids=successors))


def later_source(captured, *, changed_anchor=False, only_new_anchor=False):
    backend, root, snapshot, _rendering, original = captured
    source = snapshot.source
    raw = backend.transcript_store.reconstruct_raw(source.id, source_revision=source.source_revision)
    records = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    original_index = int(owner.parse_qs(owner.urlparse(original[0].locator).fragment)["exchange"][0])
    if changed_anchor:
        for row in records:
            message = row.get("payload") or {}
            if message.get("role") == "user" and message.get("turn_id") == f"turn-{original_index}":
                message["content"][0]["text"] = "An altered original authored condition."
    count = len(owner._parse_exchanges(_rendering)[1])
    for role, text in [("user", "A later-only task instruction, never original evidence."),
                       ("assistant", "A later-only assistant response.")]:
        records.append({"type": "response_item", "payload": {"type": "message", "turn_id": f"turn-{count + 1}",
            "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}})
    native = ("\n".join(json.dumps(row) for row in records) + "\n").encode()
    rendering = _native_codex_authored_texts(native)[0]
    later = run(persist_session_snapshot(backend,
        Observation(session_id=source.session_id, client=source.client, raw_content=rendering,
            content_type="transcript", timestamp=datetime.now(timezone.utc), metadata={}),
        project_name="demo", project_root=str(root), client=source.client, session_id=source.session_id,
        source_kind=source.source_kind, source_uri=source.source_uri, source_text=rendering,
        raw_bytes=native, native_input_bytes=native, parser_version="codex-jsonl-v1", capture_config=MergedConfig()))
    assert later.source.id == source.id and later.source.source_revision != source.source_revision
    indexes = [count + 1] if only_new_anchor else [original_index, count + 1]
    refs = []
    for index in indexes:
        window = render_distill_exchange_windows(rendering, [index])[0]
        locator = backend.transcript_store.db_path.resolve().as_uri() + "#" + urlencode({
            "source_id": source.id, "source_revision": later.source.source_revision, "exchange": index})
        refs.append(KnowledgeSource(project_name="demo", knowledge_id="new-comparison", source_kind="user_statement",
            locator=locator, content_sha256=window["content_sha256"], verified_at=datetime.now(timezone.utc)))
    return refs


def test_same_source_current_knowledge_is_comparison_without_handles_or_evidence(captured):
    entry, refs = seed(captured)
    backend = captured[0]
    before = backend.structured_store._canonical.get_payload_json("knowledge_entries", entry.id)
    comparison = compare(captured)
    assert len(comparison) == 1
    assert comparison[0] == {**_entry_version_snapshot(entry), "comparison_only": True,
        "kind": "current_knowledge_comparison_not_source_evidence"}
    assert not any(key in comparison[0] for key in ["handle", "sources", "verification_refs", "allowed_targets"])
    assert backend.structured_store._canonical.get_payload_json("knowledge_entries", entry.id) == before
    assert run(backend.structured_store.knowledge_store.list_sources(entry.id)) == refs


def test_current_successors_remain_separate_from_read_only_comparison(captured):
    entry, _sources = seed(captured)
    assert compare(captured, successors=[entry.id]) == []
    other, _sources = seed(captured, identity="other-comparison")
    assert [row["id"] for row in compare(captured, successors=[entry.id])] == [other.id]


@pytest.mark.parametrize("fault", ["other_project", "report", "missing_source", "source_project", "role",
    "other_source", "missing_revision", "digest"])
def test_invalid_or_foreign_comparison_sources_are_skipped(captured, fault):
    source = captured[-1][0]
    project, report, sources = "demo", False, [source]
    if fault == "other_project":
        project = "other-project"
    elif fault == "report":
        report = True
    elif fault == "missing_source":
        sources = []
    elif fault == "source_project":
        sources = [source.model_copy(update={"project_name": "other-project"})]
    elif fault == "role":
        sources = [source.model_copy(update={"source_kind": "transcript"})]
    elif fault in {"other_source", "missing_revision"}:
        parsed = owner.urlparse(source.locator)
        query = {key: values[0] for key, values in owner.parse_qs(parsed.fragment).items()}
        query["source_id" if fault == "other_source" else "source_revision"] = "unavailable"
        sources = [source.model_copy(update={"locator": parsed._replace(fragment=urlencode(query)).geturl()})]
    else:
        sources = [source.model_copy(update={"content_sha256": "0" * 64})]
    seed(captured, project=project, report=report, sources=sources)
    assert compare(captured) == []


@pytest.mark.parametrize("field,value", [("session_id", "another-session"), ("client", "hermes")])
def test_comparison_revision_cannot_cross_session_or_native_client(captured, monkeypatch, field, value):
    seed(captured)
    backend, root, snapshot, rendering, _sources = captured
    original = backend.transcript_store.get_revision(snapshot.source.id, snapshot.source.source_revision)
    actual = backend.transcript_store.get_revision
    monkeypatch.setattr(backend.transcript_store, "get_revision", lambda *args, **kwargs:
        actual(*args, **kwargs).model_copy(update={field: value}))
    windows = render_distill_exchange_windows(rendering, range(1, len(owner._parse_exchanges(rendering)[1]) + 1))
    result = run(owner._current_source_comparison(backend, project_name="demo", project_root=root,
        original_revision=original, original_windows=windows, successor_ids=[]))
    assert result == []


def test_valid_cross_revision_shared_anchor_is_comparison_not_later_evidence(captured):
    refs = later_source(captured)
    entry, _sources = seed(captured, sources=refs)
    comparison = compare(captured)
    assert [row["id"] for row in comparison] == [entry.id]
    assert comparison[0]["comparison_only"] is True
    assert "later-only" not in json.dumps(comparison)


@pytest.mark.parametrize("changed_anchor,only_new_anchor", [(True, False), (False, True)])
def test_cross_revision_requires_an_exact_original_authored_anchor(captured, changed_anchor, only_new_anchor):
    refs = later_source(captured, changed_anchor=changed_anchor, only_new_anchor=only_new_anchor)
    seed(captured, sources=refs)
    assert compare(captured) == []


def test_bad_optional_comparison_does_not_change_original_prepare_source_or_targets(coverage, captured):
    backend, root, _job, successor, item, checkpoint, notes = coverage
    before = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id="original-coverage", item=item, checkpoint=checkpoint, notes=notes, include_current_comparison=True))
    seed(captured, sources=[captured[-1][0].model_copy(update={"content_sha256": "0" * 64})])
    after = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id="original-coverage", item=item, checkpoint=checkpoint, notes=notes, include_current_comparison=True))
    assert before["binding"] == after["binding"] and before["packet"] == after["packet"]
    assert before["successors"] == after["successors"] == [_entry_version_snapshot(successor)]
    assert after["comparison_current_truth"] == []


def test_prepare_adds_only_comparison_and_preserves_original_full_evidence(coverage, captured):
    backend, root, _job, successor, item, checkpoint, notes = coverage
    entry, _sources = seed(captured, sources=later_source(captured))
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id="original-coverage", item=item, checkpoint=checkpoint, notes=notes, include_current_comparison=True))
    assert [row["id"] for row in prepared["comparison_current_truth"]] == [entry.id]
    assert prepared["binding"]["successor_ids"] == [successor.id]
    assert prepared["binding"]["source_revision"] == captured[2].source.source_revision
    assert prepared["packet"]["source_revision"] == captured[2].source.source_revision
    assert "later-only" not in json.dumps(prepared["packet"])
