"""Native-account identity through shared writes and fresh ordinary recall."""
import asyncio

from harness_mem.autonomous.models import CandidateVerificationDecision, CandidateVerificationPoint, CandidateScopeSegment
from harness_mem.core.schemas.source_report import report_output_scope_text


def report_judgment(report, title):
    written = report.model_copy(update={"topic_title": None if title == report.legacy_title() else title})
    scope = report_output_scope_text(written)
    return CandidateVerificationDecision(points=[CandidateVerificationPoint(
        candidate_index=0, semantic_support="supported", future_scope="durable",
        source_use="reusable_knowledge", reason="Check the whole native account, title, text and evidence boundary.",
        scope_segments=[CandidateScopeSegment(text=scope, source_use="reusable_knowledge",
            future_scope="durable", standalone=True, content_role="claim", source_support="supported")],
    )]).model_dump(mode="json")


def test_identical_reports_from_two_native_accounts_persist_and_replay(tmp_path, monkeypatch):
    from test_shared_write_core import _backend, _report, _source_for, _point
    from harness_mem.commands.knowledge_assimilation import record_assimilation_result, recover_committed_assimilation
    from harness_mem.core.schemas.knowledge import KnowledgeCandidate
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend
    from harness_mem.read_knowledge import search_current_knowledge

    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        expected = {}
        try:
            for session in ("native-account-a", "native-account-b"):
                report = _report(session_id=session, period="that session (date unknown)")
                source = await _source_for(report, backend)
                candidate = KnowledgeCandidate(id="candidate-" + session, project_name="demo",
                    candidate_type="memory", statement=report.text, source_report=report)
                point = _point("Widget cache limit", report.text, report=report)
                point["candidate_id"] = candidate.id
                ids = await record_assimilation_result(backend, candidate=candidate, point=point,
                    project_root=tmp_path, source_refs=[source])
                before = {row.id: row.to_dict() for row in await backend.structured_store.knowledge_store.list_entries("demo")}
                again = await record_assimilation_result(backend, candidate=candidate, point=point,
                    project_root=tmp_path, source_refs=[source])
                assert again == ids
                recovered = await recover_committed_assimilation(backend, project_name="demo",
                    project_root=tmp_path, points=[point])
                assert recovered == ids
                assert {row.id: row.to_dict() for row in await backend.structured_store.knowledge_store.list_entries("demo")} == before
                expected[session] = ids[0]
            assert len(set(expected.values())) == 2
        finally:
            await backend.close()
        fresh = LocalMemoryBackend(tmp_path / "data")
        await fresh.init()
        try:
            rows = await search_current_knowledge(fresh, query="Widget cache", project_name="demo", limit=100)
            assert {row.source_report.session_id: row.id for row in rows} == expected
            assert len({row.source_report.source_id for row in rows}) == 2
            assert len({row.source_report.text for row in rows}) == 1
            assert all(row.statement == row.source_report.render_statement() for row in rows)
        finally:
            await fresh.close()
    asyncio.run(exercise())


def test_pre_identity_report_commit_recovers_without_migration(tmp_path, monkeypatch):
    """Emulate only the old deterministic ID producer on a temporary actual commit."""
    from uuid import uuid5, NAMESPACE_URL
    from test_shared_write_core import _backend, _report, _source_for, _point
    from harness_mem.commands import knowledge_assimilation as owner
    from harness_mem.core.schemas.knowledge import KnowledgeCandidate

    def legacy_id(project_name, item):
        identity = "\0".join([project_name, *item["topic_path"], item["title"], item["statement"]])
        return str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge:{identity}"))

    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            report = _report(session_id="legacy-native-account")
            source = await _source_for(report, backend)
            candidate = KnowledgeCandidate(id="legacy-committed-candidate", project_name="demo",
                candidate_type="memory", statement=report.text, source_report=report)
            point = _point("Widget cache limit", report.text, report=report)
            point["candidate_id"] = candidate.id
            with monkeypatch.context() as old_producer:
                old_producer.setattr(owner, "_knowledge_item_id", legacy_id)
                ids = await owner.record_assimilation_result(backend, candidate=candidate, point=point,
                    project_root=tmp_path, source_refs=[source])
            store = backend.structured_store.knowledge_store
            before = {row.id: row.to_dict() for row in await store.list_entries("demo")}
            recovered = await owner.recover_committed_assimilation(backend, project_name="demo",
                project_root=tmp_path, points=[point])
            assert recovered == ids
            again = await owner.record_assimilation_result(backend, candidate=candidate, point=point,
                project_root=tmp_path, source_refs=[source])
            assert again == ids
            assert {row.id: row.to_dict() for row in await store.list_entries("demo")} == before
        finally:
            await backend.close()
    asyncio.run(exercise())
