"""Project names are context labels; frozen native roots still define scope.

All seven adapters read fictional native files/containers through the real MCP
dispatcher. No host application, model, global settings or real memory is used.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import sqlite3
from types import SimpleNamespace

import pytest

from harness_mem.adapters.source_inspection import HOSTS, normalized_root
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.core.schemas.observation import Observation
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.embedding.model_loader import temporarily_disable_embeddings
from harness_mem.mcp import server, tool_handlers
from harness_mem.qualification.automatic_projects_outcome_probe import create_native_fixture
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.transcript_store import TranscriptStore


def _rpc(name, arguments):
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert response is not None and "error" not in response, response
    return json.loads(response["result"]["content"][0]["text"])


def _success(name, arguments):
    result = _rpc(name, arguments)
    assert result.get("success") is True, result
    return result


def _profile(context, name, root, filename="workspace.json"):
    path = context.data / "profiles" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"project_name": name, "project_root": str(root)}), encoding="utf-8")
    return path


def _historical_source(context, name, root, session_id="historical"):
    """Persist old source metadata in the actual isolated transcript ledger."""
    source = TranscriptSource(
        id=f"fictional-{session_id}", project_name=name, project_root=str(root),
        client="codex", session_id=session_id, source_kind="jsonl",
        source_uri=(context.base / f"{session_id}.jsonl").as_uri(),
        source_revision="sha256:" + "0" * 64,
        raw_sha256="0" * 64, normalized_sha256="0" * 64, status="missing",
    )
    with closing(TranscriptStore(context.data)) as ledger:
        ledger.save_source(source)


@pytest.fixture(params=[False, True], ids=["native-files", "native-containers-and-archives"])
def native_context(tmp_path, monkeypatch, request):
    roots = [tmp_path / "alpha" / "project", tmp_path / "beta" / "project"]
    for root in roots:
        root.mkdir(parents=True)
    fixture = create_native_fixture(tmp_path, roots, native_containers=request.param)
    context = SimpleNamespace(base=tmp_path, roots=roots, data=tmp_path / "data", native=fixture)
    original = {path: path.read_bytes() for path in (tmp_path / "native").rglob("*") if path.is_file()}
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: fixture["factories"][client]())
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: context.data)
    monkeypatch.setattr(tool_handlers, "_cost_surface_budgets_provider", lambda _: None)
    # Shared implementation edits must not turn a context test into version drift.
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "project-context-fixture")
    session_inventory._PAGE_CACHE.clear()
    yield context
    session_inventory._PAGE_CACHE.clear()
    assert all(path.read_bytes() == content for path, content in original.items())


@pytest.fixture
def runtime_context(native_context, monkeypatch):
    with temporarily_disable_embeddings():
        backend = LocalMemoryBackend(native_context.data)
        asyncio.run(backend.init())
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
        monkeypatch.setattr(tool_handlers, "_ingest_sessions", lambda **_: pytest.fail("selected batch broad-ingested host history"))
        native_context.backend = backend
        try:
            yield native_context
        finally:
            asyncio.run(backend.close())


def _inventory(context, index=0, name=None):
    arguments = {"project_root": str(context.roots[index])}
    if name is not None:
        arguments["project_name"] = name
    return _success("inspect_sessions", arguments)


def _row(context, client="codex", index=0, name=None):
    rows = _inventory(context, index, name)["sessions"]
    return next(row for row in rows if row["client"] == client and row["ownership"] == "project")


def _start(context, row, index=0, name="project"):
    return _success("prepare_session_distill", {
        "project_name": name, "project_root": str(context.roots[index]), "batch_sessions": [row],
    })


@pytest.mark.parametrize("client", HOSTS)
@pytest.mark.parametrize("selector", ["automatic", "job", "session", "defer"])
def test_single_session_never_claims_same_label_other_root(runtime_context, client, selector):
    context = runtime_context
    snapshot = asyncio.run(persist_session_snapshot(
        context.backend,
        Observation(session_id="other-root", client=client, raw_content="Other workspace private source.",
                    content_type="transcript", metadata={}),
        project_name="project", project_root=str(context.roots[1]), client=client,
        session_id="other-root", source_kind="jsonl", source_uri=(context.roots[1] / "source.jsonl").as_uri(),
        source_text="User: keep only this other workspace source.\n",
    ))
    job = context.backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    before = job.to_dict()
    checkpoints_before = context.backend.transcript_store.list_distill_checkpoints(job.id)
    arguments = {"project_name": "project", "project_root": str(context.roots[0]),
                 "client": client, "run_ingest": False}
    if selector == "job":
        arguments["distill_job_id"] = job.id
    elif selector == "session":
        arguments["session_id"] = job.session_id
    elif selector == "defer":
        arguments["defer_job_id"] = job.id
    payload = _rpc("prepare_session_distill", arguments)
    if selector != "automatic":
        assert payload["success"] is False, payload
    assert payload.get("distill_job_id") != job.id
    assert "Other workspace private source" not in json.dumps(payload)
    assert context.backend.transcript_store.get_distill_job(job.id).to_dict() == before
    assert context.backend.transcript_store.list_distill_checkpoints(job.id) == checkpoints_before
    assert not asyncio.run(context.backend.structured_store.knowledge_store.list_entries("project"))


def test_new_same_basename_roots_keep_same_label_and_separate_native_scope(native_context):
    context = native_context
    discovered = _success("inspect_sessions", {})
    assert discovered["scope"] == "all" and len(discovered["sessions"]) == 14
    assert {row["project_name"] for row in discovered["sessions"]} == {"global"}
    projects = session_inventory.discover_session_projects(context.data)["projects"]
    assert {item["project_root"] for item in projects} == {normalized_root(root) for root in context.roots}
    assert [item["project_name"] for item in projects] == ["project", "project"]
    assert all(item["counts"]["sessions"] == 7 for item in projects)
    for index in range(2):
        view = _inventory(context, index)
        owned = [row for row in view["sessions"] if row["ownership"] == "project"]
        assert view["project_name"] == "project"
        assert {row["client"] for row in owned} == set(HOSTS)
        assert len(owned) == 7
        assert all(row["project_root"] == normalized_root(context.roots[index]) for row in owned)
    assert not context.data.exists()


@pytest.mark.parametrize("old_root", ["current", "other", "absent", "rootless"])
def test_transcript_ledger_never_supplies_or_reserves_display_labels(native_context, old_root):
    context = native_context
    root = {"current": context.roots[0], "other": context.roots[1],
            "absent": context.base / "removed" / "project", "rootless": ""}[old_root]
    _historical_source(context, "ledger-only-label", root)
    _historical_source(context, "project", root, session_id="old-basename")
    ledger = context.data / "transcript_ledger.sqlite"
    before = ledger.read_bytes()
    result = _success("inspect_sessions", {})
    assert result["scope"] == "all"
    assert {item["project_name"] for item in result["sessions"] if item["origin"] == "native"} == {"global"}
    assert all(item["project_name"] == "project" for item in session_inventory.discover_session_projects(context.data)["projects"])
    assert _inventory(context)["project_name"] == "project"
    assert ledger.read_bytes() == before
    assert not (context.data / "profiles").exists()
    assert not (context.data / "manual-batches").exists()


def test_current_root_profile_label_survives_duplicate_profiles_and_old_ledger(native_context):
    context = native_context
    current = _profile(context, "cache workspace", context.roots[0])
    other = _profile(context, "cache workspace", context.roots[1], "other.json")
    _historical_source(context, "cache workspace", context.base / "missing" / "project")
    _historical_source(context, "obsolete label", context.roots[0], "obsolete")
    before = {path: path.read_bytes() for path in (current, other)}
    result = _success("inspect_sessions", {})
    assert result["scope"] == "all"
    assert {item["project_name"] for item in result["sessions"] if item["origin"] == "native"} == {"global"}
    assert {item["project_name"] for item in session_inventory.discover_session_projects(context.data)["projects"]} == {"cache workspace"}
    view = _inventory(context)
    assert view["project_name"] == "cache workspace"
    assert {row["project_name"] for row in view["sessions"] if row["ownership"] == "project"} == {"cache workspace"}
    assert {path: path.read_bytes() for path in before} == before


def test_profile_at_other_root_does_not_reserve_new_basename(native_context):
    context = native_context
    profile = _profile(context, "project", context.roots[1])
    before = profile.read_bytes()
    discovered = _success("inspect_sessions", {})
    assert discovered["scope"] == "all"
    assert all(item["project_name"] == "project" for item in session_inventory.discover_session_projects(context.data)["projects"])
    assert _inventory(context)["project_name"] == "project"
    assert profile.read_bytes() == before


@pytest.mark.parametrize("recorded", ["profile", "ledger-other", "ledger-absent", "ledger-rootless"])
def test_explicit_name_and_root_accepted_despite_same_label_elsewhere(runtime_context, recorded):
    context = runtime_context
    root = context.roots[1] if recorded in {"profile", "ledger-other"} else context.base / "absent" / "project"
    if recorded == "profile":
        path = _profile(context, "caller label", root)
        before = path.read_bytes()
    else:
        _historical_source(context, "caller label", "" if recorded == "ledger-rootless" else root)
    selected = _row(context, name="caller label")
    page = _success("inspect_sessions", {"action": "source", "session": selected})
    assert page["verified_session"]["project_name"] == "caller label"
    packet = _start(context, page["verified_session"], name="caller label")
    job = context.backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.project_name == "caller label"
    assert normalized_root(job.project_root) == normalized_root(context.roots[0])
    single = _success("prepare_session_distill", {
        "project_name": "caller label", "project_root": str(context.roots[0]),
        "client": "codex", "distill_job_id": job.id, "run_ingest": False,
    })
    assert single["distill_job_id"] == job.id
    if recorded == "profile":
        assert path.read_bytes() == before


def test_explicit_context_can_override_optional_current_profile_label(runtime_context):
    context = runtime_context
    path = _profile(context, "saved display", context.roots[0])
    before = path.read_bytes()
    assert _inventory(context)["project_name"] == "saved display"
    selected = _row(context, name="caller display")
    packet = _start(context, selected, name="caller display")
    job = context.backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.project_name == "caller display"
    assert normalized_root(job.project_root) == normalized_root(context.roots[0])
    assert path.read_bytes() == before


@pytest.mark.parametrize("client", HOSTS)
def test_seven_native_adapters_prepare_and_resume_same_label_at_distinct_roots(runtime_context, client):
    context = runtime_context
    _historical_source(context, "project", context.base / "removed" / "project")
    packets = []
    for index in range(2):
        selected = _row(context, client, index, "project")
        page = _success("inspect_sessions", {"action": "source", "session": selected})
        assert page["revision_verified"] and page["content"]
        assert page["verified_session"]["project_root"] == normalized_root(context.roots[index])
        packet = _start(context, page["verified_session"], index)
        job = context.backend.transcript_store.get_distill_job(packet["distill_job_id"])
        revision = context.backend.transcript_store.get_revision(job.source_id, job.source_revision)
        assert job.client == client and job.project_name == "project"
        assert normalized_root(job.project_root) == normalized_root(context.roots[index])
        assert revision.project_name == job.project_name
        assert normalized_root(revision.project_root) == normalized_root(job.project_root)
        assert context.backend.transcript_store.reconstruct_raw(job.source_id, source_revision=job.source_revision)
        resumed = _success("prepare_session_distill", {"batch_id": packet["batch_id"]})
        assert resumed["distill_job_id"] == job.id
        status = _success("inspect_sessions", {"batch_id": packet["batch_id"]})
        assert status["progress"]["selected"] == 1
        packets.append(packet)
    assert packets[0]["batch_id"] != packets[1]["batch_id"]
    assert packets[0]["distill_job_id"] != packets[1]["distill_job_id"]
    assert len(context.backend.transcript_store.list_distill_jobs(project_name="project")) == 2
    assert not asyncio.run(context.backend.structured_store.knowledge_store.list_entries("project"))


@pytest.mark.parametrize("hint", ["original", "forged-current", "omitted"])
def test_same_label_mixed_root_batch_rejected_before_import(runtime_context, hint):
    context = runtime_context
    first, second = _row(context), _row(context, index=1)
    if hint == "forged-current":
        second = {**second, "project_root": first["project_root"]}
    elif hint == "omitted":
        second = {key: value for key, value in second.items() if key not in {"project_root", "project_name"}}
    result = _rpc("prepare_session_distill", {
        "project_name": "project", "project_root": str(context.roots[0]), "batch_sessions": [first, second],
    })
    assert result["success"] is False, result
    assert context.backend.transcript_store.list_distill_jobs(project_name="project") == []
    assert context.backend.transcript_store.list_sources(project_name="project", limit=None) == []
    assert not list((context.data / "manual-batches").glob("*.json"))


@pytest.mark.parametrize("tamper", ["root", "reference", "revision"])
def test_tampered_source_reference_rejected_for_page_and_batch(runtime_context, tamper):
    context = runtime_context
    selected = _row(context, index=1 if tamper == "root" else 0)
    selected = {**selected}
    if tamper == "root":
        selected["project_root"] = str(context.roots[0])
    elif tamper == "reference":
        selected["reference_id"] = "0" * 64
    else:
        selected["source_revision"] = "sha256:" + "0" * 64
    page = _rpc("inspect_sessions", {"action": "source", "project_name": "project",
                                     "project_root": str(context.roots[0]), "session": selected})
    assert page["success"] is False, page
    batch = _rpc("prepare_session_distill", {"project_name": "project", "project_root": str(context.roots[0]),
                                             "batch_sessions": [selected]})
    assert batch["success"] is False, batch
    assert context.backend.transcript_store.list_distill_jobs(project_name="project") == []


@pytest.mark.parametrize("mismatch", ["root", "name"])
def test_frozen_batch_cannot_resume_with_different_explicit_context(runtime_context, mismatch):
    context = runtime_context
    packet = _start(context, _row(context))
    job_id = packet["distill_job_id"]
    before = context.backend.transcript_store.get_distill_job(job_id).to_dict()
    arguments = {"batch_id": packet["batch_id"], "project_name": "project", "project_root": str(context.roots[0])}
    arguments["project_root" if mismatch == "root" else "project_name"] = str(context.roots[1]) if mismatch == "root" else "other label"
    for tool in ("inspect_sessions", "prepare_session_distill"):
        result = _rpc(tool, arguments)
        assert result["success"] is False, result
    assert context.backend.transcript_store.get_distill_job(job_id).to_dict() == before
    resumed = _success("prepare_session_distill", {"batch_id": packet["batch_id"]})
    assert resumed["distill_job_id"] == job_id


@pytest.mark.parametrize("tamper", ["job-root", "revision-root", "revision-name"])
def test_frozen_batch_rechecks_persisted_job_and_revision_context(runtime_context, tamper):
    context = runtime_context
    packet = _start(context, _row(context))
    job_id = packet["distill_job_id"]
    job = context.backend.transcript_store.get_distill_job(job_id)
    # Corrupt only this fictional SQLite row; exercise public read/resume checks.
    with sqlite3.connect(context.data / "transcript_ledger.sqlite") as db:
        if tamper == "job-root":
            table, clause, keys = "distill_jobs", "id = ?", (job.id,)
        else:
            table, clause, keys = "transcript_source_revisions", "source_id = ? AND source_revision = ?", (job.source_id, job.source_revision)
        payload = json.loads(db.execute(f"SELECT data FROM {table} WHERE {clause}", keys).fetchone()[0])
        payload["project_name" if tamper == "revision-name" else "project_root"] = "other label" if tamper == "revision-name" else str(context.roots[1])
        db.execute(f"UPDATE {table} SET data = ? WHERE {clause}", (json.dumps(payload), *keys))
    status = _rpc("inspect_sessions", {"batch_id": packet["batch_id"]})
    assert status["success"] is False, status
    resumed = _rpc("prepare_session_distill", {"batch_id": packet["batch_id"]})
    assert resumed["success"] is False, resumed
    assert len(context.backend.transcript_store.list_distill_jobs(project_name="project")) == 1
    assert not asyncio.run(context.backend.structured_store.knowledge_store.list_entries("project"))
