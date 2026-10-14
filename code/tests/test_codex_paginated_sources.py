"""Same-id Desktop continuation files are independent selected sources."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.snapshot import persist_inspected_session
from harness_mem.adapters.source_inspection import inspect_native_source
from harness_mem.config.merge import MergedConfig
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


def _fragment(path: Path, root: Path, text: str) -> None:
    rows = [{"type": "session_meta", "payload": {
        "id": "fictional-thread", "cwd": str(root), "history_mode": "paginated",
    }}]
    if text:
        rows.extend([
            {"type": "event_msg", "payload": {"type": "user_message", "message": text}},
            {"type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Acknowledged."}],
            }},
            {"type": "response_item", "payload": {
                "type": "function_call_output", "output": "HOST_ONLY_SECRET",
            }},
        ])
    write_jsonl(path, rows)


@pytest.mark.parametrize("first_text", ["First decision.", ""])
@pytest.mark.parametrize("across_roots", [False, True])
def test_discovery_keeps_same_id_continuations(tmp_path, first_text, across_roots):
    current, archive = tmp_path / "sessions", tmp_path / "archived_sessions"
    root = tmp_path / "fictional-project"
    first = (current if across_roots else archive) / "rollout-first.jsonl"
    second = archive / "rollout-continuation.jsonl"
    _fragment(first, root, first_text)
    _fragment(second, root, "Later correction.")
    before = {path: path.read_bytes() for path in (first, second)}
    adapter = CodexAdapter(None, sessions_dir=current, archive_dir=archive, scope="all")
    for records in (adapter.list_sessions(), adapter.list_session_metadata()):
        assert {row["path"] for row in records} == {first, second}
        assert {row["session_id"] for row in records} == {"fictional-thread"}
    assert {path: path.read_bytes() for path in before} == before


def test_selected_continuations_keep_distinct_revisions_and_private_boundaries(tmp_path):
    async def run():
        archive = tmp_path / "archived_sessions"
        root = tmp_path / "fictional-project"
        paths = [archive / "rollout-first.jsonl", archive / "rollout-second.jsonl"]
        for path, text in zip(paths, ["First decision.", "Later correction."]):
            _fragment(path, root, text)
        before = [path.read_bytes() for path in paths]
        adapter = CodexAdapter(None, sessions_dir=tmp_path / "sessions", archive_dir=archive, scope="all")
        records = adapter.list_session_metadata()
        selected = [inspect_native_source(
            adapter, "codex", row, project_root=None, config=MergedConfig(),
        ) for row in records]
        assert all(item.readability == "readable" for item in selected)
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            results = [await persist_inspected_session(
                backend, item, project_name="fixture", project_root="", capture_config=MergedConfig(),
            ) for item in selected]
            assert len({result.source.id for result in results}) == 2
            assert len({result.source.source_revision for result in results}) == 2
            for result, item in zip(results, selected):
                raw = backend.transcript_store.reconstruct_raw(result.source.id)
                assert raw == item.captured_bytes
                assert b"HOST_ONLY_SECRET" not in raw
            assert len(backend.transcript_store.list_sources(project_name="fixture", client="codex")) == 2
        finally:
            await backend.close()
        assert [path.read_bytes() for path in paths] == before
    asyncio.run(run())
