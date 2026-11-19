"""The actual written Note uses readable reports without changing stored truth."""
from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path

from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from test_agent_report_review import CONDITION, PERIOD, RECOVERY, VALIDATION, _entries, _finalize, _point, _prepare


def test_report_note_keeps_attribution_date_conditions_and_current_storage(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("HARNESS_MEM_SESSION_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    handlers = tool_handlers
    try:
        capture, window = _prepare(backend, handlers, root, "note-source", ["Review cache recovery conditions."])
        result = _finalize(handlers, capture.distill_job_id, [
            _point(window, RECOVERY, conditions=[CONDITION], undecided_state=None),
            _point(window, VALIDATION, conditions=[], undecided_state=VALIDATION),
        ])
        assert result["success"] and result["readback_verified"], result
        entries = _entries(backend)
        note = Path(result["note"]["path"])
        raw = note.read_bytes()
        text = raw.decode("utf-8")
        assert sha256(raw).hexdigest() == result["note"]["sha256"]
        assert PERIOD in text and CONDITION in text and VALIDATION in text
        for entry in entries:
            assert entry.statement == entry.source_report.render_statement()
            assert entry.source_report.readable_statement() in text
            assert entry.statement not in text
    finally:
        asyncio.run(backend.close())
