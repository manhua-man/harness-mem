"""An explicit device session must not require a whole-device model packet."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from harness_mem.commands import session_inventory
from harness_mem.mcp import tool_handlers
from test_device_memory_flow import device as device


def test_explicit_device_session_prepares_without_project_or_inventory_packet(device):
    backend, write = device
    selected = write("selected", "For future work, keep the user-approved setting.")
    untouched = write("unrelated", "UNRELATED-BODY-MUST-NOT-BE-PREPARED")
    originals = {path: path.read_bytes() for path in (selected, untouched)}

    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="selected",
    )

    assert packet.get("success"), packet
    assert packet.get("session_id") == "selected", packet
    assert packet.get("distill_job_id") and packet.get("batch_id")
    body = packet["semantic_decision_exchanges"][0]["content"]
    assert "keep the user-approved setting" in body and "Understood." in body
    rendered = json.dumps(packet)
    assert "UNRELATED-BODY" not in rendered and "sessions" not in packet
    jobs = list(backend.transcript_store.list_distill_jobs())
    assert len(jobs) == 1 and jobs[0].session_id == "selected"
    assert jobs[0].manual_only and jobs[0].retain_source
    assert all(path.read_bytes() == original for path, original in originals.items())
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("global")) == []


def test_missing_explicit_device_session_does_not_fall_back_to_other_sources(device):
    backend, write = device
    write("other", "OTHER-SOURCE-MUST-NOT-BE-OFFERED")
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="missing",
    )
    assert packet.get("success") is False, packet
    assert "OTHER-SOURCE" not in json.dumps(packet)
    assert not list(backend.transcript_store.list_distill_jobs())


def test_explicit_device_session_still_obeys_source_capture_policy(device, tmp_path, monkeypatch):
    from harness_mem.config.merge import MergedConfig

    backend, write = device
    excluded = tmp_path / "excluded"
    excluded.mkdir()
    write("excluded", "EXCLUDED-SOURCE-BODY", roots=[excluded])
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda path: MergedConfig(capture_enabled=path is None))
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="excluded",
    )
    assert "EXCLUDED-SOURCE-BODY" not in json.dumps(packet)
    assert not list(backend.transcript_store.list_distill_jobs())


def test_explicit_device_session_does_not_ignore_disabled_ingest(device):
    backend, write = device
    write("selected", "Must not import while ingestion is disabled.")
    tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="selected", run_ingest=False,
    )
    assert not list(backend.transcript_store.list_distill_jobs())


def test_ambiguous_device_identity_does_not_choose_a_host(device, monkeypatch):
    backend, _ = device
    monkeypatch.setattr(session_inventory, "collect_session_inventory", lambda *args, **kwargs: SimpleNamespace(rows=[
        {"client": "codex", "session_id": "same"},
        {"client": "claude-code", "session_id": "same"},
    ]))
    result = tool_handlers.tool_prepare_session_distill(scope="all", session_id="same")
    assert result["success"] is False and "ambiguous" in result["error"]
    assert not list(backend.transcript_store.list_distill_jobs())
