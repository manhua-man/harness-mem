"""Worker proof transfer only; isolated source/store doubles, no native calls."""
from types import SimpleNamespace

import pytest

from test_report_original_inventory import fixture, native_vote, expand
from test_native_final_scope_transport import native_payload
from test_dream_stage4_contract import _result
from harness_mem.autonomous import worker
from harness_mem.commands.separated_assimilation import final_scope_payload, final_scope_proof
from harness_mem.commands.knowledge_assimilation import _require_new_write_final_judgment
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.source_report import SourceReport


@pytest.mark.parametrize('complete', [True, False])
def test_worker_transfers_only_independently_accepted_original_inventory(monkeypatch, tmp_path, complete):
    prepared, plan, payload, _manifest, _classification = fixture()
    evidence = SimpleNamespace(verification_reason_codes=['autonomous_final_scope_required'])
    source = SimpleNamespace(source_kind='session', content_sha256='a' * 64)

    class Store:
        async def list_sources(self, identity):
            assert identity == 'entry'
            return [source]

        async def list_evidence(self, identity):
            assert identity == 'candidate'
            return [evidence]

        async def save_evidence(self, value):
            assert value is evidence

    async def reopen(*_args, **_kwargs):
        return SimpleNamespace(verification_outcome='verified'), [
            SimpleNamespace(content='Complete immutable source for the original report.', truncated=False)]

    def invoke(_provider, action, manifest, **_kwargs):
        assert action == 'verify' and manifest['contract_version'] == 'final-knowledge-scope-v1'
        response = native_vote(manifest) if complete else native_payload(manifest)
        return _result(expand(manifest, response))

    monkeypatch.setattr('harness_mem.commands.evidence_admission.reopen_knowledge_sources', reopen)
    monkeypatch.setattr(worker, '_invoke_provider', invoke)
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=Store()))
    _result_value, updated = worker._verify_final_knowledge_scope(
        object(), backend=backend, prepared=prepared, plan=plan,
        original_manifest={'candidates': [{'sources': [{'kind': 'session',
            'content': 'Complete original assistant source, without current-knowledge authority.'}]}]},
        governed_candidate_ids=['candidate'], runtime_dir=tmp_path, heartbeat=lambda: None,
    )
    point = updated['points'][0]
    if not complete:
        assert point['disposition'] == 'defer'
        assert 'report_preservation_inventory' not in point
        assert 'final_report_original_inventory_unproved' in evidence.verification_reason_codes
        return
    assert point['report_preservation_inventory'] == payload['report_preservation_inventory']
    canonical = final_scope_payload(prepared, point)
    assert final_scope_proof(canonical) in evidence.verification_reason_codes
    parent = payload['targets'][0]
    report = SourceReport.model_validate(parent['source_report'])
    candidate = KnowledgeCandidate(id='candidate', project_name='demo', candidate_type='memory',
        statement=report.render_statement(), source_report=report)
    predecessor = KnowledgeEntry(id=parent['id'], project_name='demo',
        title=parent['title'], statement=parent['statement'], module_path=parent['topic_path'],
        source_report=report)
    # Exercise the canonical semantic gate with the exact worker-saved proof.
    _require_new_write_final_judgment(candidate, point, items=canonical['knowledge_items'],
        predecessors=[predecessor], evidence_codes=set(evidence.verification_reason_codes))
