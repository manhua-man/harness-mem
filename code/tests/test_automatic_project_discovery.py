"""Fictional native metadata → selected full source, never the real host data."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from harness_mem.adapters.source_inspection import HOSTS, metadata_project_root, normalized_root
from harness_mem.adapters.source_metadata import read_jsonl_metadata, structured_metadata_roots
from harness_mem.commands import session_inventory as inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import session_handlers, tool_handlers
from harness_mem.qualification.automatic_projects_outcome_probe import create_native_fixture


@pytest.fixture
def native(tmp_path, monkeypatch):
    projects = [tmp_path / "alpha" / "project", tmp_path / "beta" / "project"]
    for project in projects:
        project.mkdir(parents=True)
    fixture = create_native_fixture(tmp_path, projects)
    data = tmp_path / "data"
    def factory(client):
        return fixture["factories"][client]()
    monkeypatch.setattr(inventory, "build_inspection_adapter", factory)
    monkeypatch.setattr(inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: data)
    inventory._PAGE_CACHE.clear()
    yield projects, data, fixture, factory
    inventory._PAGE_CACHE.clear()


def _selection(native, client="codex"):
    projects, data, _, factory = native
    discovered = inventory.discover_session_projects(data, adapter_factory=factory)
    binding = next(item for item in discovered["projects"] if item["project_root"] == normalized_root(projects[0]))
    row = next(row for row in binding["sessions"] if row["client"] == client)
    return binding, row


def test_default_discovery_is_readonly_seven_hosts_same_names_independent(native, monkeypatch):
    projects, data, fixture, _ = native
    before = {path: path.read_bytes() for path in fixture["locations"]["codex"].parent.rglob("*") if path.is_file()}
    monkeypatch.setattr(inventory, "inspect_native_source", lambda *_args, **_kwargs: pytest.fail("read a conversation during discovery"))
    result = session_handlers.tool_inspect_sessions()
    assert result["success"] and result["scope"] == "all"
    assert {item["project_root"] for item in result["sessions"]} == {normalized_root(path) for path in projects}
    assert {item["project_name"] for item in result["sessions"]} == {"global"}
    assert len(result["sessions"]) == 14 and all(not item["revision_verified"] for item in result["sessions"])
    assert not data.exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("client", HOSTS)
def test_narrow_metadata_references_are_stable_without_friendly_name(native, client):
    projects, data, _, factory = native
    binding, row = _selection(native, client)
    narrowed = inventory.collect_session_inventory(data, project_root=projects[0], project_name="new-friendly-name",
                                                   clients=[client], adapter_factory=factory, lightweight=True)
    same = next(item for item in narrowed.rows if item["ownership"] == "project")
    assert same["reference_id"] == row["reference_id"]
    assert same["revision_verified"] is False and same["readability"] == "not_checked"
    assert same["source_revision"].startswith("metadata:") and same["processing"] == "pending"
    assert binding["project_name"] != "new-friendly-name"


def test_known_binding_wins_over_stale_name_hint(native):
    projects, data, _, _ = native
    (data / "profiles").mkdir(parents=True)
    (data / "profiles" / "one.json").write_text(json.dumps({"project_root": str(projects[0]), "project_name": "registered"}), encoding="utf-8")
    _, row = _selection(native)
    row["project_name"] = "old-name"
    name, root = inventory.resolve_session_scope(data, sessions=[row])
    assert name == "registered" and root.resolve() == projects[0].resolve()


def test_scope_does_not_guess_router_workdir(native, monkeypatch):
    projects, data, _, _ = native
    monkeypatch.chdir(projects[0])
    assert inventory.resolve_session_scope(data) is None
    result = session_handlers.tool_inspect_sessions()
    assert result["scope"] == "all" and len(result["sessions"]) == 14


def test_mixed_project_selection_rejected_before_any_write(native):
    _, data, _, factory = native
    projects = inventory.discover_session_projects(data, adapter_factory=factory)["projects"]
    with pytest.raises(ValueError, match="independently"):
        inventory.resolve_session_scope(data, sessions=[project["sessions"][0] for project in projects])
    assert not data.exists()


def test_profile_name_is_a_label_not_a_directory_reservation(native):
    projects, data, _, _ = native
    (data / "profiles").mkdir(parents=True)
    (data / "profiles" / "two.json").write_text(json.dumps({"project_root": str(projects[1]), "project_name": "reserved"}), encoding="utf-8")
    _, row = _selection(native)
    row["project_name"] = "reserved"
    name, root = inventory.resolve_session_scope(data, sessions=[row])
    assert name == "reserved" and normalized_root(root) == normalized_root(projects[0])


def test_rootless_prepare_discovers_instead_of_ingesting_router_workspace(native, monkeypatch):
    from harness_mem.mcp import distill_handlers
    projects, data, _, _ = native
    monkeypatch.chdir(projects[0])
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: pytest.fail("initialized a memory backend"))
    monkeypatch.setattr(distill_handlers, "_ingest_sessions", lambda **_: pytest.fail("imported Router workspace"))
    result = distill_handlers.tool_prepare_session_distill()
    assert result["success"] and result["prepared"] is False and len(result["sessions"]) == 14
    assert not data.exists()


def test_nonbatch_prepare_accepts_current_context_without_profile_name_reservation(native, monkeypatch):
    from harness_mem.mcp import distill_handlers
    projects, data, _, _ = native
    (data / "profiles").mkdir(parents=True)
    profile = data / "profiles" / "registered.json"
    original = json.dumps({"project_root": str(projects[1]), "project_name": "registered"})
    profile.write_text(original, encoding="utf-8")
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: SimpleNamespace(data_dir=data))
    class IngestReached(Exception):
        pass
    def intercept(**arguments):
        assert arguments["project_name"] == "registered"
        assert normalized_root(arguments["project_root"]) == normalized_root(projects[0])
        raise IngestReached
    monkeypatch.setattr(distill_handlers, "_ingest_sessions", intercept)
    with pytest.raises(IngestReached):
        distill_handlers.tool_prepare_session_distill(project_name="registered", project_root=str(projects[0]), client="codex")
    assert profile.read_text(encoding="utf-8") == original


def test_name_only_preparation_resolves_known_root_not_router(native, monkeypatch):
    from harness_mem.mcp import distill_handlers
    projects, data, _, _ = native
    (data / "profiles").mkdir(parents=True)
    (data / "profiles" / "registered.json").write_text(json.dumps({"project_root": str(projects[1]), "project_name": "registered"}), encoding="utf-8")
    monkeypatch.chdir(projects[0])
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: SimpleNamespace(data_dir=data))
    class IngestReached(Exception):
        pass
    def intercept(**arguments):
        assert normalized_root(arguments["project_root"]) == normalized_root(projects[1])
        raise IngestReached
    monkeypatch.setattr(distill_handlers, "_ingest_sessions", intercept)
    with pytest.raises(IngestReached):
        distill_handlers.tool_prepare_session_distill(project_name="registered", client="codex")


@pytest.mark.parametrize("client", HOSTS)
def test_verified_preview_reference_preserves_scope_for_preparation(native, client):
    projects, data, _, factory = native
    binding, row = _selection(native, client)
    page = inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, adapter_factory=factory)
    name, root = inventory.resolve_session_scope(data, sessions=[page["verified_session"]])
    assert name == binding["project_name"] and normalized_root(root) == normalized_root(projects[0])


def test_unavailable_root_remains_optional_context_and_can_be_selected(native):
    projects, data, fixture, _ = native
    missing = projects[0] / "does-not-exist"
    path = fixture["locations"]["codex"] / "sessions" / "rollout-fixture-codex-0.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "missing", "cwd": str(missing)}}) + "\n", encoding="utf-8")
    found = inventory.discover_session_projects(data, clients=["codex"])
    binding = next(item for item in found["projects"] if item["project_root"] == normalized_root(missing))
    assert binding["available"] is False
    _, selected_root = inventory.resolve_session_scope(data, sessions=binding["sessions"])
    assert normalized_root(selected_root) == normalized_root(missing)
    assert not data.exists()


def test_one_invalid_project_config_does_not_hide_others(native, monkeypatch):
    projects, data, _, _ = native
    def configuration(root):
        if normalized_root(root) == normalized_root(projects[0]):
            raise ValueError("fictional malformed TOML")
        return MergedConfig()
    monkeypatch.setattr(inventory, "load_merged_config", configuration)
    result = inventory.discover_session_projects(data)
    bad = next(item for item in result["projects"] if item["project_root"] == normalized_root(projects[0]))
    good = next(item for item in result["projects"] if item["project_root"] == normalized_root(projects[1]))
    assert bad["available"] is False and all(row["processing"] == "blocked" for row in bad["sessions"])
    assert good["available"] is True and len(good["sessions"]) == 7
    assert result["issues"][0]["reason"] == "project_configuration_unreadable"


def test_capture_exclusion_visible_without_export(native, monkeypatch):
    _, data, _, _ = native
    monkeypatch.setattr(inventory, "load_merged_config", lambda *_: MergedConfig(capture_ignore_clients=["codex"]))
    result = inventory.discover_session_projects(data)
    assert all(row["processing"] == "skipped" and row["readability"] == "excluded"
               for project in result["projects"] for row in project["sessions"] if row["client"] == "codex")
    assert not data.exists()


def test_paged_read_exports_only_selected_and_rechecks_changed_source(native, monkeypatch):
    projects, data, fixture, factory = native
    binding, row = _selection(native)
    reader, calls = inventory.inspect_native_source, []
    def observed(adapter, client, record, **kwargs):
        calls.append((client, record["session_id"]))
        return reader(adapter, client, record, **kwargs)
    monkeypatch.setattr(inventory, "inspect_native_source", observed)
    first = inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, page_chars=10, adapter_factory=factory)
    second = inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, offset=10, page_chars=10, adapter_factory=factory)
    assert calls == [("codex", "fixture-codex-0")]
    assert first["verified_session"]["source_revision"].startswith("sha256:")
    assert first["content_sha256"] == second["content_sha256"]
    path = fixture["locations"]["codex"] / "sessions" / "rollout-fixture-codex-0.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "changed"}]}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, offset=10, adapter_factory=factory)
    assert not data.exists()


def test_wal_creation_invalidates_cached_preview_and_ownership(native):
    projects, data, fixture, factory = native
    binding, row = _selection(native, "opencode")
    inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, adapter_factory=factory)
    path = fixture["locations"]["opencode"] / "opencode.db"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.commit()
        writer.execute("UPDATE session SET directory=? WHERE id=?", (str(projects[1]), row["session_id"]))
        writer.commit()
        with pytest.raises(ValueError, match="outside project"):
            inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, offset=1, adapter_factory=factory)


def test_changed_capture_policy_cannot_reuse_cached_text(native, monkeypatch):
    projects, data, _, factory = native
    binding, row = _selection(native)
    inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, adapter_factory=factory)
    monkeypatch.setattr(inventory, "load_merged_config", lambda *_: MergedConfig(capture_ignore_clients=["codex"]))
    with pytest.raises(ValueError):
        inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, adapter_factory=factory)


def test_source_change_during_full_read_cannot_be_cached_as_current(native, monkeypatch):
    projects, data, fixture, factory = native
    binding, row = _selection(native)
    reader = inventory.inspect_native_source
    path = fixture["locations"]["codex"] / "sessions" / "rollout-fixture-codex-0.jsonl"
    def racing_reader(*args, **kwargs):
        old = reader(*args, **kwargs)
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return old
    monkeypatch.setattr(inventory, "inspect_native_source", racing_reader)
    with pytest.raises(ValueError):
        inventory.read_session_page(data, project_root=projects[0], project_name=binding["project_name"], session=row, adapter_factory=factory)
    assert not inventory._PAGE_CACHE


def test_corroborated_working_directory_is_not_a_second_project(tmp_path):
    root, other = tmp_path / "project", tmp_path / "other"
    child = root / "src"
    assert structured_metadata_roots({"workspace_root": str(root), "cwd": str(child)}) == [str(root)]
    assert structured_metadata_roots({"workspace_root": root.as_uri(), "cwd": str(child)}) == [root.as_uri()]
    assert metadata_project_root(structured_metadata_roots({"workspace_root": str(root), "cwd": str(other)})) == ""
    assert metadata_project_root(structured_metadata_roots({"workspace_root": str(root), "project_root": str(child)})) == ""
    assert structured_metadata_roots({"content": str(root), "tool": {"cwd": str(root)}}) == []


def test_header_cache_is_metadata_only_and_returns_independent_values(tmp_path):
    path = tmp_path / "source.jsonl"
    root = tmp_path / "project"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "one", "cwd": str(root), "body": "private"}}) + "\n", encoding="utf-8")
    roots, header = read_jsonl_metadata(path, client="codex")
    assert "body" not in header
    roots.clear()
    header.clear()
    again = read_jsonl_metadata(path, client="codex")
    assert again[0] == [str(root)] and again[1]["id"] == "one"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "two", "cwd": str(root / "other")}}) + "\n", encoding="utf-8")
    assert read_jsonl_metadata(path, client="codex")[1]["id"] == "two"
