"""Fresh public callers discover progress using only temporary stores and sources."""
from pathlib import Path
import runpy

from harness_mem.mcp import tool_handlers
from harness_mem.storage.manual_batch_store import ManualBatchStore

public_history = runpy.run_path(str(Path(__file__).with_name("test_public_manual_history.py")))["public_history"]


def snapshot(data_dir):
    return {str(path.relative_to(data_dir)): path.read_bytes()
            for path in (data_dir / "manual-batches").rglob("*") if path.is_file()}


def test_fresh_discovery_preserves_pause_then_explicitly_continues(public_history):
    backend, root, write, handlers, _ = public_history
    write("fresh")
    sessions = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])["sessions"]
    packet = handlers.tool_prepare_session_distill(project_root=str(root), project_name="old-label", batch_sessions=sessions)
    assert packet["success"], packet
    held = handlers.tool_prepare_session_distill(batch_id=packet["batch_id"], pause=True)
    assert held["status"] == "paused"
    before = snapshot(backend.data_dir)
    fresh = tool_handlers
    inventory = fresh.tool_inspect_sessions(project_root=str(root), clients=["cursor"])
    assert inventory["success"], inventory
    assert inventory["batch_count"] == 1
    batch = inventory["batches"][0]
    assert batch["state"] == "paused" and batch["status"] == "paused"
    assert batch["progress"]["selected"] == batch["progress"]["remaining"] == 1
    assert inventory["batch_continuation"]["resolution"] == "unique"
    assert batch["project_name"] == "old-label"
    status = fresh.tool_inspect_sessions(**batch["inspect_arguments"])
    assert status["progress"] == batch["progress"]
    assert snapshot(backend.data_dir) == before
    passive_resume = fresh.tool_prepare_session_distill(**batch["resume_arguments"])
    assert passive_resume["status"] == "paused"
    assert snapshot(backend.data_dir) == before
    resumed = fresh.tool_prepare_session_distill(**batch["continue_arguments"])
    assert resumed["success"] and resumed["distill_job_id"] == packet["distill_job_id"]
    assert ManualBatchStore(backend.data_dir).load(packet["batch_id"], "old-label", str(root))["state"] == "active"


def test_project_device_isolation_and_ambiguous_continuation(public_history, tmp_path):
    backend, root, write, handlers, _ = public_history
    write("scope")
    store = ManualBatchStore(backend.data_dir)
    sessions = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])["sessions"]
    refs = [{key: row[key] for key in ("client", "session_id", "source_id", "source_revision", "reference_id")}
            for row in sessions]
    a = store.create("project", str(root), refs)
    b = store.create("project", str(root), refs)
    foreign = store.create("project", str(tmp_path / "other"), refs)
    device = store.create("global", "", refs, scope="all")
    before = snapshot(backend.data_dir)
    inventory = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])
    assert {row["batch_id"] for row in inventory["batches"]} == {a["batch_id"], b["batch_id"]}
    assert inventory["batch_continuation"]["resolution"] == "ambiguous"
    assert inventory["batch_continuation"]["candidate_count"] == 2
    device_inventory = handlers.tool_inspect_sessions(scope="all", clients=["cursor"])
    assert [row["batch_id"] for row in device_inventory["batches"]] == [device["batch_id"]]
    assert device_inventory["batch_continuation"]["resolution"] == "unique"
    assert not handlers.tool_inspect_sessions(project_root=str(root), batch_id=foreign["batch_id"])["success"]
    assert not handlers.tool_inspect_sessions(project_root=str(root), batch_id=device["batch_id"])["success"]
    assert snapshot(backend.data_dir) == before


def test_empty_list_creates_nothing(tmp_path):
    data = tmp_path / "absent"
    store = ManualBatchStore(data)
    assert store.list_batches(project_root=str(tmp_path)) == []
    assert store.list_batches(scope="all") == []
    assert not data.exists()
