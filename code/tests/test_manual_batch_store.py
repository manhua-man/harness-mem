"""Synthetic-only contracts for temporary manual batch persistence."""

from concurrent.futures import ThreadPoolExecutor
import json
import sys
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from harness_mem.commands.session_inventory import session_reference
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.transcript import TranscriptSourceRevision
from harness_mem.storage.manual_batch_store import ManualBatchStore
from harness_mem.transcript_chunking import transcript_source_id


@pytest.mark.skipif(sys.platform != "win32", reason="Windows delete-sharing race")
def test_atomic_publication_retries_transient_reader_sharing(batch, monkeypatch):
    import harness_mem.storage.manual_batch_store as module
    store, root, batch_id = batch
    original = module.os.replace
    calls = []

    def transient(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            error = PermissionError("fixture reader holds old manifest")
            error.winerror = 32
            raise error
        return original(source, destination)

    monkeypatch.setattr(module.os, "replace", transient)
    store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    assert len(calls) == 2
    assert store.load(batch_id, "project", root)["bindings"] == {"ref-0": "job-0"}


def selection(count=2):
    return [dict(client="codex", session_id=f"session-{i}", source_id=f"source-{i}",
                 source_revision="revision-1", reference_id=f"ref-{i}")
            for i in reversed(range(count))]


@pytest.fixture
def batch(tmp_path):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path / "project")
    manifest = store.create("project", root, selection())
    return store, root, manifest["batch_id"]


def test_freeze_reload_and_deterministic_order(tmp_path):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path / "project" / ".")
    sessions = selection()
    first = store.create("project", root, sessions)
    assert UUID(first["batch_id"]).version == 4
    second = store.create("project", root, list(reversed(sessions)))
    assert first["sessions"] == second["sessions"]
    assert first["batch_id"] != second["batch_id"]
    assert Path(first["project_root"]).is_absolute()
    assert first["version"] == 1
    sessions[0]["source_revision"] = "changed"
    first["sessions"].clear()
    loaded = ManualBatchStore(tmp_path / "data").load(first["batch_id"], "project", root)
    assert loaded["sessions"] == second["sessions"]
    assert [row["reference_id"] for row in loaded["sessions"]] == ["ref-0", "ref-1"]


def test_missing_load_and_update_are_read_only(tmp_path):
    store = ManualBatchStore(tmp_path / "absent")
    for action in (
        lambda: store.load(str(uuid4()), "p", str(tmp_path)),
        lambda: store.bind_job(str(uuid4()), "p", str(tmp_path), "r", "j"),
        lambda: store.retry_failures(str(uuid4()), "p", str(tmp_path)),
    ):
        with pytest.raises(FileNotFoundError):
            action()
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("operation", ["load", "bind_job", "record_failure", "retry_failures"])
@pytest.mark.parametrize("foreign", ["project", "root"])
def test_scope_isolation(batch, operation, foreign, tmp_path):
    store, root, batch_id = batch
    name = "other" if foreign == "project" else "project"
    root = str(tmp_path / "other") if foreign == "root" else root
    before = {p.name: p.read_bytes() for p in store.root.iterdir()}
    args = () if operation in ("load", "retry_failures") else ("ref-0", "value")
    with pytest.raises(ValueError, match="scope"):
        getattr(store, operation)(batch_id, name, root, *args)
    assert {p.name: p.read_bytes() for p in store.root.iterdir()} == before


@pytest.mark.parametrize("batch_id", ["../escape", "..\\escape", "/absolute", "invalid"])
def test_traversal_rejected(tmp_path, batch_id):
    store = ManualBatchStore(tmp_path)
    with pytest.raises(ValueError):
        store.load(batch_id, "p", str(tmp_path))
    assert not store.root.exists()


@pytest.mark.parametrize("invalid", [[], [{}], ["session"],
    [dict(selection(1)[0], body="transcript")],
    [selection(1)[0], dict(selection(1)[0], reference_id="different")],
    [selection(1)[0], dict(selection(1)[0], session_id="different")],
    [dict(selection(1)[0], source_revision="")]])
def test_invalid_selection_rejected_without_writes(tmp_path, invalid):
    store = ManualBatchStore(tmp_path)
    with pytest.raises(ValueError):
        store.create("p", str(tmp_path), invalid)
    assert not store.root.exists()


def test_root_validation_and_generated_reference(tmp_path):
    store = ManualBatchStore(tmp_path / "data")
    for root in ("relative", str(tmp_path / ".." / "escape")):
        with pytest.raises(ValueError):
            store.create("p", root, selection())
    rows = selection(1)
    del rows[0]["reference_id"]
    a = store.create("p", str(tmp_path), rows)
    b = store.create("p", str(tmp_path), rows)
    assert a["sessions"] == b["sessions"]


def test_binding_is_idempotent_and_exclusive(batch, monkeypatch):
    store, root, batch_id = batch
    expected = store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    monkeypatch.setattr(store, "_write", lambda *_: pytest.fail("idempotent call wrote"))
    assert store.bind_job(batch_id, "project", root, "ref-0", "job-0") == expected
    with pytest.raises(ValueError, match="rebound"):
        store.bind_job(batch_id, "project", root, "ref-0", "job-1")
    with pytest.raises(ValueError, match="another reference"):
        store.bind_job(batch_id, "project", root, "ref-1", "job-0")
    with pytest.raises(KeyError):
        store.bind_job(batch_id, "project", root, "unknown", "job-1")


def test_failures_survive_binding_and_stop_is_sticky(batch):
    store, root, batch_id = batch
    store.record_failure(batch_id, "project", root, "ref-0", "source unavailable")
    bound = store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    assert bound["failures"] == {"ref-0": "source unavailable"}
    stopped = store.record_failure(batch_id, "project", root, "ref-1", "interrupted", True)
    assert stopped["state"] == "stopped"
    with pytest.raises(ValueError, match="stopped"):
        store.bind_job(batch_id, "project", root, "ref-1", "job-1")
    with pytest.raises(ValueError, match="overwritten"):
        store.record_failure(batch_id, "project", root, "ref-0", "different")
    assert store.load(batch_id, "project", root) == stopped
    assert store.bind_job(batch_id, "project", root, "ref-0", "job-0") == stopped


def test_concurrent_independent_instances_do_not_lose_bindings(tmp_path):
    data = tmp_path / "data"
    root = str(tmp_path)
    store = ManualBatchStore(data)
    manifest = store.create("p", root, selection(12))
    barrier = Barrier(12)

    def bind(index):
        barrier.wait()
        return ManualBatchStore(data).bind_job(
            manifest["batch_id"], "p", root, f"ref-{index}", f"job-{index}")

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(bind, range(12)))
    loaded = store.load(manifest["batch_id"], "p", root)
    assert loaded["bindings"] == {f"ref-{i}": f"job-{i}" for i in range(12)}
    assert loaded["sessions"] == manifest["sessions"]


def test_concurrent_conflicting_binding_has_one_winner(batch):
    store, root, batch_id = batch
    barrier = Barrier(2)

    def bind(job):
        barrier.wait()
        try:
            ManualBatchStore(store.root.parent).bind_job(
                batch_id, "project", root, "ref-0", job)
            return job
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [job for job in pool.map(bind, ["job-a", "job-b"]) if job]
    assert len(winners) == 1
    assert store.load(batch_id, "project", root)["bindings"] == {"ref-0": winners[0]}


@pytest.mark.parametrize("failure_point", ["fsync", "replace"])
def test_interrupted_write_preserves_previous_manifest_and_releases_lock(
    batch, monkeypatch, failure_point
):
    store, root, batch_id = batch
    before = store.load(batch_id, "project", root)

    def interrupted(*_):
        raise KeyboardInterrupt("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(f"harness_mem.storage.manual_batch_store.os.{failure_point}", interrupted)
        with pytest.raises(KeyboardInterrupt):
            store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    assert store.load(batch_id, "project", root) == before
    assert not list(store.root.glob("*.tmp"))
    result = store.bind_job(batch_id, "project", root, "ref-1", "job-1")
    assert result["bindings"] == {"ref-1": "job-1"}
    assert len(list(store.root.glob("*.json"))) == 1


def test_corrupt_version_or_state_is_not_accepted(batch):
    store, root, batch_id = batch
    path = store.root / f"{batch_id}.json"
    original = store.load(batch_id, "project", root)
    for field, value in (("version", 2), ("state", "completed"),
                         ("bindings", {"outside-selection": "job"})):
        path.write_text(json.dumps(dict(original, **{field: value})), encoding="utf-8")
        with pytest.raises(ValueError):
            store.load(batch_id, "project", root)


def test_fingerprint_is_frozen_across_updates_and_reload(tmp_path):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path)
    fingerprint = "sha256:" + "a" * 64
    manifest = store.create("p", root, selection(), runtime_fingerprint=fingerprint)
    batch_id = manifest["batch_id"]
    manifest["runtime_fingerprint"] = "caller-mutated"
    store.bind_job(batch_id, "p", root, "ref-0", "job-0")
    store.record_failure(batch_id, "p", root, "ref-0", "retry needed")
    store.retry_failures(batch_id, "p", root)
    store.record_failure(batch_id, "p", root, "ref-1", "redline", True)
    loaded = ManualBatchStore(store.root.parent).load(batch_id, "p", root)
    assert loaded["runtime_fingerprint"] == fingerprint
    assert loaded["sessions"] == manifest["sessions"]
    assert loaded["bindings"] == {"ref-0": "job-0"}


@pytest.mark.parametrize("invalid", ["", " ", " padded", "line\nbreak", 123, {}, "x" * 1025])
def test_invalid_fingerprint_rejected_on_create_and_load(tmp_path, invalid):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path)
    with pytest.raises(ValueError, match="runtime_fingerprint"):
        store.create("p", root, selection(), runtime_fingerprint=invalid)
    assert not store.root.exists()
    manifest = store.create("p", root, selection())
    manifest["runtime_fingerprint"] = invalid
    path = store.root / f"{manifest['batch_id']}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="runtime_fingerprint"):
        store.load(manifest["batch_id"], "p", root)


def test_optional_and_legacy_fingerprint_load_without_writing(batch):
    store, root, batch_id = batch
    manifest = store.load(batch_id, "project", root)
    assert manifest["runtime_fingerprint"] is None
    path = store.root / f"{batch_id}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["runtime_fingerprint"] is None
    del manifest["runtime_fingerprint"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    assert store.load(batch_id, "project", root)["runtime_fingerprint"] is None
    assert path.read_bytes() == before


def test_explicit_retry_clears_only_active_failures(batch, monkeypatch):
    store, root, batch_id = batch
    store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    store.record_failure(batch_id, "project", root, "ref-0", "failure 0")
    before = store.record_failure(batch_id, "project", root, "ref-1", "failure 1")
    retried = store.retry_failures(batch_id, "project", root)
    assert retried == dict(before, failures={})
    assert store.load(batch_id, "project", root) == retried
    with monkeypatch.context() as patch:
        patch.setattr(store, "_write", lambda *_: pytest.fail("no-op retry wrote"))
        assert store.retry_failures(batch_id, "project", root) == retried
    new_failure = store.record_failure(batch_id, "project", root, "ref-0", "new attempt")
    assert new_failure["failures"] == {"ref-0": "new attempt"}


def test_stopped_retry_cannot_clear_failures(batch):
    store, root, batch_id = batch
    stopped = store.record_failure(batch_id, "project", root, "ref-0", "redline", True)
    path = store.root / f"{batch_id}.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="stopped"):
        store.retry_failures(batch_id, "project", root)
    assert path.read_bytes() == before
    assert store.load(batch_id, "project", root) == stopped


def test_already_completed_is_sorted_unique_and_preserved(tmp_path):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path)
    prior = ["ref-1", "ref-0", "ref-1"]
    manifest = store.create("p", root, selection(), already_completed=prior)
    batch_id = manifest["batch_id"]
    assert manifest["already_completed"] == ["ref-0", "ref-1"]
    prior.clear()
    manifest["already_completed"].clear()
    bound = store.bind_job(batch_id, "p", root, "ref-0", "old-job")
    failed = store.record_failure(batch_id, "p", root, "ref-1", "retry needed")
    retried = store.retry_failures(batch_id, "p", root)
    stopped = store.record_failure(batch_id, "p", root, "ref-1", "redline", True)
    loaded = ManualBatchStore(store.root.parent).load(batch_id, "p", root)
    for result in (bound, failed, retried, stopped, loaded):
        assert result["already_completed"] == ["ref-0", "ref-1"]
        assert result["sessions"] == bound["sessions"]
        assert result["bindings"] == {"ref-0": "old-job"}


@pytest.mark.parametrize("invalid", [["unknown"], ["ref-0", "unknown"], "ref-0", [1]])
def test_already_completed_rejects_invalid_subset_on_create_and_load(tmp_path, invalid):
    store = ManualBatchStore(tmp_path / "data")
    root = str(tmp_path)
    with pytest.raises(ValueError, match="already_completed"):
        store.create("p", root, selection(), already_completed=invalid)
    assert not store.root.exists()
    manifest = store.create("p", root, selection())
    assert manifest["already_completed"] == []
    manifest["already_completed"] = invalid
    path = store.root / f"{manifest['batch_id']}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="already_completed"):
        store.load(manifest["batch_id"], "p", root)


@pytest.mark.parametrize("invalid", [["ref-1", "ref-0"], ["ref-0", "ref-0"], None])
def test_load_rejects_noncanonical_completed_references(batch, invalid):
    store, root, batch_id = batch
    manifest = store.load(batch_id, "project", root)
    manifest["already_completed"] = invalid
    path = store.root / f"{batch_id}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="already_completed"):
        store.load(batch_id, "project", root)


def test_legacy_completed_default_is_read_only(batch):
    store, root, batch_id = batch
    manifest = store.load(batch_id, "project", root)
    del manifest["already_completed"]
    del manifest["runtime_fingerprint"]
    path = store.root / f"{batch_id}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    loaded = store.load(batch_id, "project", root)
    assert loaded["already_completed"] == []
    assert loaded["runtime_fingerprint"] is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("reason", ["selected_source_processing_failed", "completion_verification_failed"])
def test_existing_failure_escalates_to_stopped_preserving_reason(batch, monkeypatch, reason):
    store, root, batch_id = batch
    store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    before = store.record_failure(
        batch_id, "project", root, "ref-0", "selected_source_processing_failed",
    )
    stopped = store.record_failure(
        batch_id, "project", root, "ref-0", reason, stop_batch=True,
    )
    assert stopped == dict(before, state="stopped")
    assert ManualBatchStore(store.root.parent).load(batch_id, "project", root) == stopped
    monkeypatch.setattr(store, "_write", lambda *_: pytest.fail("repeated stop wrote"))
    assert store.record_failure(
        batch_id, "project", root, "ref-0", reason, stop_batch=True,
    ) == stopped
    with pytest.raises(ValueError, match="stopped"):
        store.retry_failures(batch_id, "project", root)


@pytest.mark.parametrize("failure_point", ["fsync", "replace"])
def test_failure_escalation_is_atomic_on_interruption(batch, monkeypatch, failure_point):
    store, root, batch_id = batch
    before = store.record_failure(batch_id, "project", root, "ref-0", "original failure")
    path = store.root / f"{batch_id}.json"
    original_bytes = path.read_bytes()

    def interrupted(*_):
        raise KeyboardInterrupt("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(f"harness_mem.storage.manual_batch_store.os.{failure_point}", interrupted)
        with pytest.raises(KeyboardInterrupt):
            store.record_failure(
                batch_id, "project", root, "ref-0", "readback failed", stop_batch=True,
            )
    assert path.read_bytes() == original_bytes
    assert store.load(batch_id, "project", root) == before
    assert not list(store.root.glob("*.tmp"))
    assert store.record_failure(
        batch_id, "project", root, "ref-0", "readback failed", stop_batch=True,
    ) == dict(before, state="stopped")


def test_pause_and_continue_keep_failures_and_block_new_binds(batch, monkeypatch):
    store, root, batch_id = batch
    store.bind_job(batch_id, "project", root, "ref-0", "job-0")
    failed = store.record_failure(batch_id, "project", root, "ref-0", "kept")
    paused = store.pause(batch_id, "project", root)
    assert paused["state"] == "paused"
    assert paused["failures"] == {"ref-0": "kept"}
    assert paused["bindings"] == {"ref-0": "job-0"}
    assert paused["sessions"] == failed["sessions"]
    with monkeypatch.context() as patch:
        patch.setattr(store, "_write", lambda *_: pytest.fail("paused batch wrote"))
        assert store.pause(batch_id, "project", root)["state"] == "paused"
        with pytest.raises(ValueError, match="paused"):
            store.retry_failures(batch_id, "project", root)
        with pytest.raises(ValueError, match="paused"):
            store.bind_job(batch_id, "project", root, "ref-1", "job-1")
    resumed = store.resume_paused(batch_id, "project", root)
    assert resumed["state"] == "active"
    assert resumed["failures"] == {"ref-0": "kept"}
    assert resumed["bindings"] == {"ref-0": "job-0"}
    with monkeypatch.context() as patch:
        patch.setattr(store, "_write", lambda *_: pytest.fail("active resume wrote"))
        assert store.resume_paused(batch_id, "project", root)["state"] == "active"
    stopped = store.record_failure(batch_id, "project", root, "ref-1", "redline", True)
    path = store.root / f"{batch_id}.json"
    held = path.read_bytes()
    for action in (
        lambda: store.pause(batch_id, "project", root),
        lambda: store.resume_paused(batch_id, "project", root),
        lambda: store.retry_failures(batch_id, "project", root),
    ):
        with pytest.raises(ValueError, match="stopped"):
            action()
    assert path.read_bytes() == held
    assert store.load(batch_id, "project", root) == stopped


def test_legacy_active_and_stopped_manifests_load_without_rewrite(batch):
    store, root, batch_id = batch
    path = store.root / f"{batch_id}.json"
    active = path.read_bytes()
    loaded = store.load(batch_id, "project", root)
    assert loaded["state"] == "active"
    assert path.read_bytes() == active
    assert set(json.loads(path.read_text(encoding="utf-8"))) == set(loaded) - set()
    payload = json.loads(active)
    payload["state"] = "stopped"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    held = path.read_bytes()
    stopped = store.load(batch_id, "project", root)
    assert stopped["state"] == "stopped"
    assert path.read_bytes() == held
    assert "paused" not in json.loads(held)


def _job(**overrides):
    fields = dict(
        id="job-bound", idempotency_key="job-bound", project_name="global", project_root="",
        client="codex", session_id="conversation", source_id="source-bound",
        source_revision="sha256:" + "a" * 64, manual_only=False,
    )
    fields.update(overrides)
    return SessionDistillJob(**fields)


def _revision(job, *, raw, uri):
    return TranscriptSourceRevision(
        source_id=job.source_id, source_revision=job.source_revision,
        project_name=job.project_name, project_root=job.project_root,
        client=job.client, session_id=job.session_id, source_kind="codex", source_uri=uri,
        raw_sha256=raw, normalized_sha256=raw, raw_size_bytes=4, normalized_size_bytes=4,
    )


def test_bound_revision_does_not_keep_later_revisions_manual(tmp_path):
    absent = ManualBatchStore(tmp_path / "absent")
    assert absent.owns_job(_job(manual_only=True), None)
    assert absent.owns_job(_job(manual_only=False), None) is False

    uri = "file:///fictional/device-session.jsonl"
    meta = transcript_source_id(
        client="codex", project_name="metadata-source", session_id="conversation", source_uri=uri,
    )
    hint = session_reference("codex", "conversation", meta, "metadata:native")
    store = ManualBatchStore(tmp_path / "device")
    manifest = store.create("global", "", [hint], scope="all")
    batch_id = manifest["batch_id"]
    selected = _job()
    selected_revision = _revision(selected, raw="a" * 64, uri=uri)
    later = _job(
        id="job-later", idempotency_key="job-later", source_revision="sha256:" + "b" * 64,
        manual_only=True,
    )
    later_revision = _revision(later, raw="b" * 64, uri=uri)
    assert store.owns_job(selected, selected_revision)
    assert store.owns_job(later, later_revision)
    store.record_failure(batch_id, "global", "", hint["reference_id"], "fixture_stop", stop_batch=True)
    assert store.owns_job(selected, selected_revision)
    assert store.load(batch_id, "global", "")["state"] == "stopped"

    exact = session_reference("codex", "conversation", selected.source_id, selected.source_revision)
    project = ManualBatchStore(tmp_path / "project")
    root = str(tmp_path / "workspace")
    reference = session_reference("cursor", "sess", "source-1", "sha256:" + "c" * 64)
    created = project.create("project", root, [reference])
    project_root = created["project_root"]
    bound = _job(
        id="project-job", idempotency_key="project-job", project_name="project",
        project_root=project_root, client="cursor", session_id="sess", source_id="source-1",
        source_revision="sha256:" + "c" * 64,
    )
    bound_revision = _revision(bound, raw="c" * 64, uri="file:///fictional/project.jsonl")
    sibling = _job(
        id="project-later", idempotency_key="project-later", project_name="project",
        project_root=project_root, client="cursor", session_id="sess", source_id="source-1",
        source_revision="sha256:" + "d" * 64, manual_only=False,
    )
    sibling_revision = _revision(sibling, raw="d" * 64, uri="file:///fictional/project.jsonl")
    assert project.owns_job(bound, bound_revision)
    assert project.owns_job(sibling, sibling_revision) is False
    project.bind_job(created["batch_id"], "project", project_root, reference["reference_id"], bound.id)
    sibling.manual_only = True
    assert project.owns_job(bound, bound_revision)
    assert project.owns_job(sibling, sibling_revision) is False
    project.pause(created["batch_id"], "project", project_root)
    assert project.owns_job(bound, bound_revision)
    assert project.owns_job(sibling, sibling_revision) is False
    project.record_failure(
        created["batch_id"], "project", project_root, reference["reference_id"], "redline", stop_batch=True,
    )
    assert project.owns_job(bound, bound_revision)
    assert project.owns_job(sibling, sibling_revision) is False
    assert exact["source_revision"].startswith("sha256:")
