"""Exercise actual worker preparation, not just a hand-built prompt manifest."""
import asyncio
import json

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.autonomous.provider import ProviderError, _build_prompt
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config import merge
from harness_mem.config.merge import MergedConfig
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_worker_supplies_all_native_messages_before_semantic_decision(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".harness-mem.toml").write_text('[distill.autonomous]\nenabled=true\n', encoding="utf-8")
    data = tmp_path / "data"
    monkeypatch.setattr(merge, "_user_config_path", lambda: data / "config.toml")
    monkeypatch.setattr(merge, "_legacy_user_config_path", lambda: data / "config.json")
    backend = LocalMemoryBackend(data)
    asyncio.run(backend.init())
    messages = []
    records = [{"type":"session_meta", "payload":{"id":"coverage-source", "cwd":str(project)}}]
    for index in range(28):
        role = "user" if index % 5 == 0 else "assistant"
        body = f"Exact native body {index:02d}. Keep complete message context."
        if index == 0:
            body += " Project Delta requires explicit approval before changing its selected settings."
        messages.append(body)
        records.append({"type":"response_item", "payload":{"type":"message", "role":role,
            "content":[{"type":"input_text" if role == "user" else "output_text", "text":body}]}})
    source = tmp_path / "native.jsonl"
    original = "".join(json.dumps(r) + "\n" for r in records).encode()
    source.write_bytes(original)
    adapter = CodexAdapter(backend, project_root=project)
    snapshot = asyncio.run(adapter.sync_session(source, "coverage-source", "coverage"))
    captured = []

    class CoverageProvider:
        name = "coverage-only"

        def decide(self, manifest, **_kwargs):
            prompt = _build_prompt(manifest)
            evidence = json.loads(prompt.split("<session_evidence>")[1].split("</session_evidence>")[0])
            body = "\n".join(e["content"] for e in evidence["exchanges"])
            assert len(evidence["exchanges"]) == 6
            assert evidence["session_outline"] == []
            assert all(body.count(message) == 1 for message in messages)
            assert [body.index(message) for message in messages] == sorted(body.index(message) for message in messages)
            captured.append(True)
            raise ProviderError("coverage probe stops before model generation", kind="unrecoverable")

    try:
        result = run_autonomous_distill_batch(backend, project_name="coverage", project_root=project,
            config=MergedConfig(distill_autonomous_enabled=True), trigger_id="coverage-source",
            client="codex", provider=CoverageProvider(), max_jobs=1, preferred_job_id=snapshot.distill_job_id)
        assert captured == [True], result
        assert source.read_bytes() == original
        assert asyncio.run(backend.structured_store.knowledge_store.list_entries("coverage")) == []
    finally:
        asyncio.run(backend.close())
