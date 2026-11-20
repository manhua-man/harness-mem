from hashlib import sha256
import json

import pytest

from harness_mem.commands import manual_distill
from harness_mem.distill import Distill
from harness_mem.storage.manual_batch_store import ManualBatchStore
from test_manual_session_flow import manual_fixture as manual_fixture


@pytest.mark.parametrize("device_scope", [False, True])
def test_retry_after_native_binding_failed_owns_its_checkpoints(manual_fixture, monkeypatch, device_scope):
    backend, root, write = manual_fixture
    write("retry-binding")
    agent = Distill(backend.data_dir)
    scope = {} if device_scope else {"project_root": str(root)}
    rows = agent.sessions(clients=["cursor"], **scope)["sessions"]
    persist = manual_distill.persist_inspected_session

    async def fail_binding(*args, **kwargs):
        if kwargs.get("expected_source_revision"):
            raise ValueError("native file changed during inspection")
        return await persist(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(manual_distill, "persist_inspected_session", fail_binding)
        failed = agent.prepare(sessions=rows, **scope)
    assert failed["error"] == "selected_native_binding_failed"
    store = ManualBatchStore(backend.data_dir)
    scope_name, scope_root = store.read_scope(failed["batch_id"])
    original = store.load(failed["batch_id"], scope_name, str(scope_root or ""))
    assert (original.get("scope") == "all") == device_scope
    old_job, = original["bindings"].values()
    if not device_scope:
        # A pre-fix retry could record the earlier stop as a failure of its own.
        propagated = store.create(scope_name, str(scope_root), original["sessions"])
        ref, = original["bindings"]
        store.bind_job(propagated["batch_id"], scope_name, str(scope_root), ref, old_job)
        store.record_failure(propagated["batch_id"], scope_name, str(scope_root), ref,
                             "manual_batch_stopped", stop_batch=True)
    retry = agent.prepare(sessions=rows, **scope)
    assert retry["success"], retry
    job_id = retry["distill_job_id"]
    assert job_id != old_job
    chunk, = retry["chunks"]
    receipt = agent.checkpoint(job_id, chunk["chunk_id"], retry["lease_owner"], {"summary": "Reviewed the source."})
    assert receipt["completed_chunk_count"] == 1
    assert agent.prepare(batch_id=retry["batch_id"])["distill_job_id"] == job_id
    with pytest.raises(ValueError, match="manual_batch_stopped"):
        agent.checkpoint(old_job, chunk["chunk_id"], retry["lease_owner"], {"summary": "stale"})
    assert agent.prepare(batch_id=failed["batch_id"], retry_failures=True)["error"] == "batch_stopped"
    assert store.load(failed["batch_id"], scope_name, str(scope_root or "")) == original


def test_default_manual_reading_resumes_from_the_next_complete_chunk(manual_fixture):
    backend, root, write = manual_fixture
    path = write("long-reading", text="Review this project's records.")
    turns = ["".join(f"Length regression record {turn}-{line}.\n" for line in range(50)).rstrip()
             for turn in range(70)]
    assert sum(map(len, turns)) > 96000
    with path.open("a", encoding="utf-8") as stream:
        for body in turns:
            for role, content in (("user", body), ("assistant", "Received.")):
                stream.write("\n" + json.dumps({
                    "role": role, "message": {"content": [{"type": "text", "text": content}]},
                }))
    agent = Distill(backend.data_dir)
    inventory = agent.sessions(project_root=str(root), clients=["cursor"])
    packet = agent.prepare(sessions=inventory["sessions"], project_root=str(root))
    assert packet["success"] and packet["expected_chunk_count"] >= 4, packet
    batch_id, job_id = packet["batch_id"], packet["distill_job_id"]
    pages = []
    while packet.get("chunks"):
        row, = packet["chunks"]
        assert row["chunk_index"] == len(pages)
        page = row["raw_content"]
        assert len(page) == row["char_end"] - row["char_start"]
        assert sha256(page.encode()).hexdigest() == row["content_sha256"]
        pages.append(page)
        receipt = agent.checkpoint(job_id, row["chunk_id"], packet["lease_owner"], {"page": len(pages)})
        assert receipt["completed_chunk_count"] == len(pages)
        if len(pages) == 1:
            assert agent.prepare(batch_id=batch_id, pause=True)["paused"]
            agent = Distill(backend.data_dir)
            assert agent.prepare(batch_id=batch_id)["paused"]
            packet = agent.prepare(batch_id=batch_id, continue_batch=True)
        else:
            packet = agent.prepare(batch_id=batch_id)
        assert packet["success"] and packet["distill_job_id"] == job_id
    assert packet["distill_status"] == "reviewing"
    assert "".join(pages).encode("utf-8") == path.read_bytes()
    assert [item["result"]["page"] for item in packet["chunk_results"]] == list(range(1, len(pages) + 1))
