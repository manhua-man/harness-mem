"""Ordinary extraction receives current meanings before proposing duplicates."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from test_dream_complete_user_context import captured as captured
from test_source_coverage_current_comparison import later_source, seed
from harness_mem.autonomous.provider import _build_prompt
from harness_mem.autonomous.worker import build_provider_manifest
from harness_mem.commands import distill_current_knowledge as owner
from harness_mem.core.schemas.source_report import SourceReport


def run(value):
    return asyncio.run(value)


def compare(captured):
    backend, root, snapshot, _rendering, _sources = captured
    return run(owner.current_source_knowledge(backend, job=SimpleNamespace(
        project_name='demo', session_id=snapshot.source.session_id, client=snapshot.source.client,
        source_id=snapshot.source.id, source_revision=snapshot.source.source_revision), project_root=root))


def test_committed_current_meaning_available_without_mutation_or_whole_exchange_skip(captured):
    backend, _root, _snapshot, _rendering, _sources = captured
    entry, refs = seed(captured)
    before = backend.structured_store._canonical.get_payload_json('knowledge_entries', entry.id)
    rows = compare(captured)
    assert len(rows) == 1 and rows[0]['id'] == entry.id
    assert rows[0]['statement'] == entry.statement
    assert rows[0]['source_exchanges'][0]['exchange_index'] == 75
    assert rows[0]['kind'] == 'current_knowledge_comparison_not_source_evidence'
    assert rows[0]['comparison_only'] is True
    assert not any(k in rows[0] for k in ['covered_ranges', 'skip_exchanges', 'handle', 'verification_refs'])
    assert backend.structured_store._canonical.get_payload_json('knowledge_entries', entry.id) == before
    assert run(backend.structured_store.knowledge_store.list_sources(entry.id)) == refs


def test_appended_revision_matches_unchanged_source_anchor_not_only_revision_identity(captured):
    seed(captured)
    refs = later_source(captured)
    revision = parse_qs(urlparse(refs[0].locator).fragment)['source_revision'][0]
    newer = captured[0].transcript_store.get_source(captured[2].source.id)
    assert newer.source_revision == revision != captured[2].source.source_revision
    changed = (captured[0], captured[1], SimpleNamespace(source=newer), captured[3], captured[4])
    rows = compare(changed)
    assert len(rows) == 1 and rows[0]['source_exchanges'][0]['source_revision'] == captured[2].source.source_revision


def test_changed_original_anchor_is_not_marked_already_committed(captured):
    seed(captured)
    later_source(captured, changed_anchor=True)
    source = captured[0].transcript_store.get_source(captured[2].source.id)
    changed = (captured[0], captured[1], SimpleNamespace(source=source), captured[3], captured[4])
    assert compare(changed) == []


def test_unproved_current_revision_role_cannot_inherit_old_authorship(captured, monkeypatch):
    seed(captured)
    monkeypatch.setattr(owner, '_source_report_author_indexes', lambda *_a,**_k: None)
    assert compare(captured) == []


@pytest.mark.parametrize('fault', ['deleted', 'other_project', 'missing_source', 'source_project',
    'other_source', 'missing_revision', 'digest', 'duplicate_query', 'role'])
def test_unproved_or_noncurrent_entry_never_suppresses_extraction(captured, fault):
    source = captured[-1][0]
    project, sources = 'demo', [source]
    if fault == 'other_project':
        project = 'other'
    elif fault == 'missing_source':
        sources = []
    elif fault == 'source_project':
        sources = [source.model_copy(update={'project_name':'other'})]
    elif fault == 'digest':
        sources = [source.model_copy(update={'content_sha256':'0'*64})]
    elif fault in {'other_source', 'missing_revision', 'duplicate_query', 'role'}:
        parsed = urlparse(source.locator)
        query = {k:v[0] for k,v in parse_qs(parsed.fragment).items()}
        if fault == 'role':
            query['role'] = 'assistant'
        else:
            query['source_id' if fault == 'other_source' else 'source_revision'] = 'missing'
        locator = parsed._replace(fragment=urlencode(query)).geturl()
        if fault == 'duplicate_query':
            locator = source.locator + '&exchange=75'
        sources = [source.model_copy(update={'locator':locator})]
    entry, _refs = seed(captured, project=project, sources=sources)
    if fault == 'deleted':
        captured[0].structured_store._canonical.apply_payload_transaction(idempotency_key='isolated-delete',
                mutations=[{'operation':'delete','collection':'knowledge_entries','entity_id':entry.id,'project_name':'demo'}])
    assert compare(captured) == []


@pytest.mark.parametrize('field,value', [('session_id','other'), ('client','hermes'), ('project_root','C:/other')])
def test_current_job_scope_mismatch_is_not_a_comparison(captured, monkeypatch, field, value):
    seed(captured)
    actual = captured[0].transcript_store.get_revision
    monkeypatch.setattr(captured[0].transcript_store, 'get_revision', lambda *a,**k:
        actual(*a,**k).model_copy(update={field:value}))
    assert compare(captured) == []


def test_typed_assistant_report_preserves_authority_and_can_be_compared(captured):
    backend, _root, snapshot, _rendering, refs = captured
    report = SourceReport(speaker='assistant', period='unknown', session_id=snapshot.source.session_id,
        source_id=snapshot.source.id, source_revision=snapshot.source.source_revision,
        exchange_indexes=[75], text='A bounded assistant report.')
    parsed = urlparse(refs[0].locator)
    query = {k:v[0] for k,v in parse_qs(parsed.fragment).items()}
    query['role'] = 'assistant'
    ref = refs[0].model_copy(update={'source_kind':'source_report',
        'locator':parsed._replace(fragment=urlencode(query)).geturl()})
    entry, sources = seed(captured, report=True, sources=[ref])
    # Replace only isolated fixture attribution to match the actual source role.
    updated = entry.model_copy(update={'source_report':report,'title':report.render_title(),
        'statement':report.render_statement()})
    backend.structured_store._canonical.apply_payload_transaction(idempotency_key='isolated-report', mutations=[{
        'operation':'upsert','collection':'knowledge_entries','entity_id':entry.id,'payload':updated.to_dict()}])
    rows = compare(captured)
    assert len(rows) == 1 and rows[0]['source_report']['speaker'] == 'assistant'
    assert rows[0]['source_exchanges'][0]['role'] == 'assistant'
    assert rows[0]['statement'] == report.render_statement()


def test_prompt_first_compares_complete_meaning_but_keeps_new_and_missing_claims(captured):
    entry, _refs = seed(captured)
    windows = [{'exchange_index':75,'content_sha256':captured[-1][0].content_sha256,
        'content':'User: Already retained choice. Additional new condition must still be extracted.\nAssistant outcome: New report.'}]
    manifest = build_provider_manifest({'semantic_decision_exchanges':windows,
        'semantic_evidence':{'exchange_count':1}})
    manifest['current_source_knowledge'] = compare(captured)
    prompt = _build_prompt(manifest)
    assert entry.statement in prompt and entry.id in prompt
    assert 'Additional new condition must still be extracted.' in prompt and 'New report.' in prompt
    assert 'Before selecting points' in prompt and 'NOT a processed whole exchange' in prompt
    assert 'Shared topic or overlapping words do not establish complete coverage' in prompt
    assert json.loads(prompt.split('<session_evidence>',1)[1].split('</session_evidence>',1)[0])['current_source_knowledge'] == manifest['current_source_knowledge']


def test_empty_comparison_keeps_legacy_extraction_prompt_exact():
    manifest = build_provider_manifest({})
    assert _build_prompt(manifest) == _build_prompt({**manifest,'current_source_knowledge':[]})
