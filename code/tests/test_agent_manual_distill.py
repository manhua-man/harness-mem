from hashlib import sha256
import json

from harness_mem.distill import Distill
from test_manual_session_flow import manual_fixture as manual_fixture


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
