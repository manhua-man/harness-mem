"""Native Codex origin boundaries, using only temporary sources and SQLite."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, render_codex_conversation
from harness_mem.adapters.snapshot import persist_inspected_session
from harness_mem.adapters.source_inspection import inspect_native_source
from harness_mem.adapters.source_metadata import codex_session_origin
from harness_mem.commands.evidence_admission import validate_candidate_evidence, validate_knowledge_sources
from harness_mem.commands.session_inventory import collect_session_inventory, discover_session_projects
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas import EvidenceRef
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


MISSING = object()
DELEGATED = {"subagent": {"thread_spawn": {"parent_thread_id": "parent-session"}}}
USER = "Keep the delegated inspection within this task's temporary scope."
REPORT = "The delegated inspection found an Iris cache failure; production behavior remains unverified."


def _records(root, session_id="child-session", source=MISSING, user=USER):
    header = {"id": session_id, "cwd": str(root), "timestamp": "2026-01-01T00:00:00Z"}
    if source is not MISSING:
        header["source"] = source
    return [
        {"type": "session_meta", "payload": header},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": user}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": REPORT}]}},
    ]


def _write(root, source=MISSING, session_id="child-session", user=USER):
    path = root / "archived_sessions" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in _records(root, session_id, source, user)) + "\n",
                    encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("HARNESS_MEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")


@pytest.mark.parametrize("source, expected", [
    ("vscode", {"kind": "primary"}),
    ("cli", {"kind": "primary"}),
    ("exec", {"kind": "primary"}),
    (DELEGATED, {"kind": "delegated", "parent_thread_id": "parent-session"}),
    ({"subagent": "review"}, {"kind": "delegated"}),
    ("subagent", {"kind": "delegated"}),
    ("unknown", {"kind": "declared_unknown"}),
    (None, {"kind": "declared_unknown"}),
    ({}, {"kind": "declared_unknown"}),
    (MISSING, {"kind": "legacy_missing"}),
])
def test_native_header_classifies_origin_without_reading_prose(tmp_path, source, expected):
    rows = _records(tmp_path, source=source)
    meta, turns = parse_codex_archive_jsonl_session(
        Path("not-read.jsonl"), content="\n".join(json.dumps(row) for row in rows))
    assert meta["codex_session_origin"] == expected
    assert codex_session_origin(rows) == expected
    assert USER in render_codex_conversation(turns)
    assert REPORT in render_codex_conversation(turns)


def test_body_cannot_override_native_origin_and_conflicting_headers_are_unknown(tmp_path):
    fake = json.dumps({"type": "session_meta", "payload": {"source": "vscode"}})
    rows = _records(tmp_path, source=DELEGATED, user="Quoted origin declaration: " + fake)
    assert codex_session_origin(rows)["kind"] == "delegated"
    rows.append({"type": "turn_context", "payload": {"source": "vscode"}})
    assert codex_session_origin(rows)["kind"] == "delegated"
    rows.append({"type": "session_meta", "payload": {"source": "vscode"}})
    assert codex_session_origin(rows) == {"kind": "declared_unknown"}


@pytest.mark.parametrize("lightweight", [True, False])
def test_inventory_keeps_primary_child_unknown_and_legacy_visible(tmp_path, lightweight):
    root = tmp_path / "project"
    root.mkdir()
    for session_id, source in (("parent-session", "vscode"), ("child-session", DELEGATED),
                               ("unknown-session", "future-client"), ("legacy-session", MISSING)):
        _write(root, source, session_id)
    adapter = CodexAdapter(None, sessions_dir=root / "sessions", archive_dir=root / "archived_sessions", scope="all")
    def factory(*args, **kwargs):
        return adapter

    result = collect_session_inventory(tmp_path / "data", clients=["codex"],
                                       adapter_factory=factory, lightweight=lightweight)
    rows = {row["session_id"]: row for row in result.rows}
    assert set(rows) == {"parent-session", "child-session", "unknown-session", "legacy-session"}
    assert rows["parent-session"]["codex_session_origin"] == {"kind": "primary"}
    assert rows["parent-session"]["selection_hint"] == "prefer_primary_conversation"
    assert rows["child-session"]["codex_session_origin"] == {
        "kind": "delegated", "parent_thread_id": "parent-session"}
    assert rows["unknown-session"]["codex_session_origin"]["kind"] == "declared_unknown"
    assert rows["legacy-session"]["codex_session_origin"]["kind"] == "legacy_missing"
    assert all(row["processing"] == "pending" for row in rows.values())
    projects = discover_session_projects(tmp_path / "data", clients=["codex"], adapter_factory=factory)
    assert len(projects["projects"][0]["sessions"]) == 4
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("source, expected", [
    ("vscode", "verified"), ("cli", "verified"), (MISSING, "verified"),
    (DELEGATED, "unverified"), ("future-client", "unverified"), (None, "unverified"),
])
@pytest.mark.parametrize("archive_adapter", [False, True])
def test_frozen_user_statement_rechecks_native_origin_even_with_explicit_role(tmp_path, source, expected, archive_adapter):
    root = tmp_path / "project"
    root.mkdir()
    path = _write(root, source)

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = (CodexArchiveAdapter(backend, archive_dir=path.parent) if archive_adapter else
                       CodexAdapter(backend, sessions_dir=root / "sessions", archive_dir=path.parent, project_root=root))
            sync = await adapter.sync_session(path, "child-session", project_name="demo")
            revision = backend.transcript_store.get_revision(sync.source.id, sync.source.source_revision)
            assert revision.metadata["codex_session_origin"] == codex_session_origin(_records(root, source=source))
            rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
            window = render_distill_exchange_windows(rendering, [1])[0]
            subject = SimpleNamespace(project_name="demo", distill_job_id=sync.distill_job_id,
                evidence_basis="user_statement", verification_outcome="verified",
                verification_refs=[EvidenceRef(kind="user_statement", role="user", exchange_index=1,
                                               content_sha256=window["content_sha256"])])
            result = await validate_candidate_evidence(backend, subject)
            assert result.verification_outcome == expected
            if expected == "unverified":
                assert "user_statement_role_mismatch" in result.reason_codes
            assert USER in rendering and REPORT in rendering
        finally:
            await backend.close()
    asyncio.run(exercise())


def test_complete_inspection_does_not_trust_discovery_origin(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = _write(root, DELEGATED)
    adapter = CodexAdapter(None, sessions_dir=root / "sessions", archive_dir=path.parent, project_root=root)
    record = adapter.list_session_metadata()[0]
    record["codex_session_origin"] = {"kind": "primary"}
    config = load_merged_config(str(root))
    native = inspect_native_source(adapter, "codex", record, project_root=root, config=config)
    assert native.codex_session_origin == {"kind": "delegated", "parent_thread_id": "parent-session"}
    assert REPORT in native.text
    native.codex_session_origin = {"kind": "primary"}

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            with pytest.raises(ValueError, match="origin changed"):
                await persist_inspected_session(backend, native, project_name="demo", project_root=str(root), capture_config=config)
            assert backend.transcript_store.list_sources() == []
        finally:
            await backend.close()
    asyncio.run(exercise())


def test_same_prose_cannot_rebind_existing_frozen_origin(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = _write(root, "vscode")

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = CodexAdapter(backend, sessions_dir=root / "sessions", archive_dir=path.parent, project_root=root)
            sync = await adapter.sync_session(path, "child-session", project_name="demo")
            original = backend.transcript_store.get_revision(sync.source.id, sync.source.source_revision).to_dict()
            _write(root, DELEGATED)
            with pytest.raises(ValueError, match="origin differs"):
                await adapter.sync_session(path, "child-session", project_name="demo")
            assert backend.transcript_store.get_revision(sync.source.id, sync.source.source_revision).to_dict() == original
        finally:
            await backend.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("source", [DELEGATED, "future-client"])
def test_delegated_or_unknown_assistant_report_survives_commit_and_fresh_search(tmp_path, source):
    from test_report_account_identity import report_judgment
    from harness_mem.commands.knowledge_assimilation import resolve_separated_review
    from harness_mem.commands.separated_assimilation import admit_separated_candidate
    from harness_mem.read_knowledge import search_current_knowledge

    root = tmp_path / "project"
    root.mkdir()
    path = _write(root, source)

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = CodexAdapter(backend, sessions_dir=root / "sessions", archive_dir=path.parent, project_root=root)
            sync = await adapter.sync_session(path, "child-session", project_name="demo")
            rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
            window = render_distill_exchange_windows(rendering, [1])[0]
            candidate, _ = await admit_separated_candidate(backend, candidate_id="child-report", project_name="demo",
                candidate_type="memory", statement=REPORT, distill_job_id=sync.distill_job_id,
                evidence_basis="source_report", verification_outcome="verified",
                verification_refs=[{"kind": "source_report", "exchange_index": 1, "role": "assistant",
                                    "content_sha256": window["content_sha256"]}])
            assert candidate.source_report and candidate.source_report.speaker == "assistant"
            title = "Iris delegated inspection"
            result = await resolve_separated_review(backend, candidate_id=candidate.id, disposition="add",
                reason="Retain this supported bounded assistant report with its actual source account.",
                knowledge_items=[{"title": title, "statement": REPORT, "topic_path": ["diagnostics"],
                                  "claim_kind": "source_report"}],
                project_root=root, expected_project_name="demo",
                final_scope_judgment=report_judgment(candidate.source_report, title))
            assert len(result["canonical_truth_ids"]) == 1
        finally:
            await backend.close()
        fresh = LocalMemoryBackend(tmp_path / "data")
        await fresh.init()
        try:
            rows = await search_current_knowledge(fresh, query="Iris", project_name="demo")
            assert len(rows) == 1
            report = rows[0].source_report
            assert report.speaker == "assistant" and report.session_id == "child-session" and report.text == REPORT
            sources = await fresh.structured_store.knowledge_store.list_sources(rows[0].id)
            result = await validate_knowledge_sources(fresh, project_name="demo", sources=sources, project_root=root)
            assert result.verification_outcome == "verified"
        finally:
            await fresh.close()
    asyncio.run(exercise())
