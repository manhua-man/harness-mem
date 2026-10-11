from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType

from harness_mem.diagnostic_events import (
    DiagnosticRun,
    append_run_event,
    load_run_events,
    run_event_path,
    diagnostic_parent_id,
)


def test_concurrent_diagnostic_contexts_do_not_change_environment(tmp_path, monkeypatch):
    import asyncio
    import os

    monkeypatch.setenv("HARNESS_MEM_DEBUG_PARENT_RUN_ID", "external-parent")
    before = dict(os.environ)

    async def child(index):
        run = DiagnosticRun(tmp_path, operation="dream", run_id=f"run-{index}")
        with run.activate_children():
            await asyncio.sleep(0)
            assert diagnostic_parent_id() == run.run_id
            nested = DiagnosticRun(tmp_path, operation="distill", run_id=f"nested-{index}")
            with nested.activate_children():
                await asyncio.sleep(0)
                assert diagnostic_parent_id() == nested.run_id
            assert diagnostic_parent_id() == run.run_id

    async def exercise():
        await asyncio.gather(child(1), child(2))
    asyncio.run(exercise())
    assert diagnostic_parent_id() == "external-parent"
    assert dict(os.environ) == before


def test_provider_events_only_surround_actual_call(tmp_path):
    from types import SimpleNamespace
    from harness_mem.autonomous.worker import _invoke_provider

    run = DiagnosticRun(tmp_path, operation="autonomous")
    def generate(*args, **kwargs):
        events, _ = load_run_events(tmp_path)
        assert [event["stage"] for event in events] == ["provider_started"]
        return "result"
    with run.activate_children():
        assert _invoke_provider(SimpleNamespace(generate=generate), "generate", {},
                                runtime_dir=tmp_path, heartbeat=None) == "result"
    events, _ = load_run_events(tmp_path)
    assert [event["stage"] for event in events] == ["provider_started", "provider_finished"]


def test_completed_wrapper_does_not_invent_commit_or_readback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from harness_mem.mcp import distill_handlers

    backend = SimpleNamespace(data_dir=tmp_path, transcript_store=SimpleNamespace(
        get_distill_job=lambda _: None,
    ))
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: backend)
    packet = {"promoted_items": []}
    core_result = {"success": True, "distill_status": "completed",
                   "answer_packet": packet, "promotion": {"answer_packet": packet}}
    monkeypatch.setattr(distill_handlers, "_tool_finalize_session_distill_core",
                        lambda **_: core_result)
    result = distill_handlers.tool_finalize_session_distill("fixture", "job-1", {})
    events, _ = load_run_events(tmp_path)
    # A generic completed flag cannot establish a result without the stored job.
    assert [event["stage"] for event in events] == ["accepted", "started", "failed"]
    assert result["success"] is False
    assert result["reason_codes"] == ["promotion_write_unreadable"]
    assert "answer_packet" not in result
    assert core_result["promotion"]["answer_packet"] == packet


def test_readback_event_requires_current_entry_and_search_match(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from harness_mem.mcp import distill_handlers
    import harness_mem.read_knowledge as reads

    entry = SimpleNamespace(id="knowledge-1", statement="fixture fact")
    store = SimpleNamespace(get_entry=AsyncMock(return_value=entry))
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store))
    summary = {"promoted": 1, "points": [{"disposition": "add",
                                          "canonical_truth_ids": [entry.id]}]}
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(reads, "search_current_knowledge", search)
    run = DiagnosticRun(tmp_path, operation="distill")
    with run.activate_children():
        error = asyncio.run(distill_handlers._promotion_commit_error(
            backend, project_name="fixture", promotion_summary=summary))
        assert error == "promotion_write_unreadable"
        assert load_run_events(tmp_path)[0] == []
        search.return_value = [entry]
        assert asyncio.run(distill_handlers._promotion_commit_error(
            backend, project_name="fixture", promotion_summary=summary)) is None
    events, _ = load_run_events(tmp_path)
    assert [event["stage"] for event in events] == ["readback_verified"]


def test_provider_exception_does_not_emit_finished(tmp_path):
    import pytest
    from types import SimpleNamespace
    from harness_mem.autonomous.worker import _invoke_provider

    def generate(*args, **kwargs):
        raise RuntimeError("fixture failure")
    run = DiagnosticRun(tmp_path, operation="autonomous")
    with run.activate_children(), pytest.raises(RuntimeError, match="fixture failure"):
        _invoke_provider(SimpleNamespace(generate=generate), "generate", {},
                         runtime_dir=tmp_path, heartbeat=None)
    assert [event["stage"] for event in load_run_events(tmp_path)[0]] == ["provider_started"]


def _load_debugger() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "harness-mem-debug"
        / "scripts"
        / "debug.py"
    )
    spec = importlib.util.spec_from_file_location("harness_mem_debug_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_debug_databases(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    transcript = data_dir / "transcript_ledger.sqlite"
    connection = sqlite3.connect(transcript)
    connection.executescript(
        """
        CREATE TABLE distill_jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE transcript_chunks (
            source_id TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO distill_jobs(id, data) VALUES (?, ?)",
        (
            "job-1",
            json.dumps(
                {
                    "id": "job-1",
                    "project_name": "fixture",
                    "session_id": "session-1",
                    "source_id": "source-1",
                    "source_revision": "revision-1",
                    "status": "completed",
                }
            ),
        ),
    )
    connection.execute(
        "INSERT INTO transcript_chunks VALUES (?, ?, ?, ?)",
        (
            "source-1",
            "revision-1",
            0,
            json.dumps(
                {
                    "chunk_index": 0,
                    "content_sha256": "sha256:chunk",
                    "raw_content": "private transcript text",
                }
            ),
        ),
    )
    connection.commit()
    connection.close()

    canonical = data_dir / "store_v2" / "canonical.sqlite"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(canonical)
    connection.execute("CREATE TABLE knowledge_entries (project_id TEXT)")
    connection.execute("INSERT INTO knowledge_entries VALUES (?)", ("fixture",))
    connection.commit()
    connection.close()

    structured = data_dir / "structured_index.sqlite"
    connection = sqlite3.connect(structured)
    connection.execute("CREATE TABLE dream_runs (project_name TEXT)")
    connection.execute("INSERT INTO dream_runs VALUES (?)", ("fixture",))
    connection.commit()
    connection.close()


def test_diagnostic_events_are_redacted_and_bad_lines_are_reported(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    diagnostic = DiagnosticRun(
        data_dir,
        operation="hook",
        project_name="fixture",
        project_root=tmp_path / "project",
        references={"job_id": "job-1"},
    )
    diagnostic.emit("accepted", "running")
    diagnostic.emit(
        "failed",
        "failed",
        error={
            "kind": "provider_http_error",
            "message": "Authorization: Bearer bearer-secret API_KEY=api-secret",
        },
    )
    path = run_event_path(data_dir)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n[]\n")

    events, malformed = load_run_events(data_dir)

    assert malformed == 2
    assert [event["stage"] for event in events] == ["accepted", "failed"]
    assert events[0]["schema_version"] == "harness_mem.run_event.v1"
    assert events[0]["run_id"] == diagnostic.run_id
    assert events[1]["duration_ms"] >= 0
    error_text = json.dumps(events[1]["error"])
    assert "bearer-secret" not in error_text
    assert "api-secret" not in error_text


def test_diagnostic_write_failure_does_not_escape_runtime(tmp_path: Path) -> None:
    data_dir = tmp_path / "data-file"
    data_dir.write_text("not a directory", encoding="utf-8")

    assert (
        append_run_event(
            data_dir,
            run_id="run-1",
            operation="hook",
            stage="accepted",
            status="running",
        )
        is None
    )


def test_debug_inspect_and_bundle_keep_reads_read_only_and_hide_source_by_default(
    tmp_path: Path,
    capsys,
) -> None:
    debugger = _load_debugger()
    data_dir = tmp_path / "data"
    _create_debug_databases(data_dir)
    diagnostic = DiagnosticRun(
        data_dir,
        operation="hook",
        project_name="fixture",
        project_root=tmp_path / "project",
        references={"job_id": "job-1"},
    )
    diagnostic.emit("accepted", "running")
    diagnostic.emit("started", "running")
    diagnostic.emit("queued", "completed")

    tracked = [
        data_dir / "transcript_ledger.sqlite",
        data_dir / "store_v2" / "canonical.sqlite",
        data_dir / "structured_index.sqlite",
    ]
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked
    }
    exit_code = debugger.main(
        [
            "inspect",
            "--run-id",
            diagnostic.run_id,
            "--data-dir",
            str(data_dir),
            "--json",
        ]
    )
    output = capsys.readouterr().out
    report = json.loads(output)

    assert exit_code == 0
    assert report["status"] == "completed"
    assert report["evidence_mode"] == "event_timeline"
    assert "readback_verified_event_missing" not in report["evidence_gaps"]
    assert report["linked_evidence"]
    assert "private transcript text" not in output
    assert all(
        (path.stat().st_mtime_ns, path.read_bytes()) == before[path]
        for path in tracked
    )

    assert (
        debugger.main(
            [
                "inspect",
                "--latest",
                "--project-root",
                str(tmp_path / "project"),
                "--data-dir",
                str(data_dir),
                "--json",
            ]
        )
        == 0
    )
    latest = json.loads(capsys.readouterr().out)
    assert latest["run"]["run_id"] == diagnostic.run_id

    bundle = tmp_path / "bundle.json"
    assert (
        debugger.main(
            [
                "bundle",
                "--run-id",
                diagnostic.run_id,
                "--data-dir",
                str(data_dir),
                "--output",
                str(bundle),
            ]
        )
        == 0
    )
    assert "private transcript text" not in bundle.read_text(encoding="utf-8")

    source_bundle = tmp_path / "source-bundle.json"
    assert (
        debugger.main(
            [
                "bundle",
                "--run-id",
                diagnostic.run_id,
                "--data-dir",
                str(data_dir),
                "--output",
                str(source_bundle),
                "--include-source",
            ]
        )
        == 0
    )
    assert "private transcript text" in source_bundle.read_text(encoding="utf-8")


def test_debug_legacy_snapshot_is_explicitly_incomplete(
    tmp_path: Path,
    capsys,
) -> None:
    debugger = _load_debugger()
    data_dir = tmp_path / "data"
    receipt_dir = data_dir / "hook_runtime"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "legacy.json").write_text(
        json.dumps(
            {
                "trigger_id": "trigger-1",
                "state": "failed",
                "error": {
                    "kind": "provider_http_error",
                    "message": "Authorization: Bearer old-secret",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = debugger.main(
        [
            "inspect",
            "--trigger-id",
            "trigger-1",
            "--data-dir",
            str(data_dir),
            "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["evidence_mode"] == "legacy_snapshot"
    assert report["status"] == "failed"
    assert "no_diagnostic_run_events" in report["evidence_gaps"]
    assert "old-secret" not in json.dumps(report)


def test_debug_events_json_stops_after_terminal_event(
    tmp_path: Path,
    capsys,
) -> None:
    debugger = _load_debugger()
    data_dir = tmp_path / "data"
    diagnostic = DiagnosticRun(data_dir, operation="hook")
    diagnostic.emit("accepted", "running")
    diagnostic.emit("answer_gate", "running")
    diagnostic.emit("sqlite_committed", "running")
    diagnostic.emit("readback_verified", "running")
    diagnostic.emit("completed", "completed")

    assert (
        debugger.main(
            [
                "events",
                "--run-id",
                diagnostic.run_id,
                "--data-dir",
                str(data_dir),
                "--follow",
                "--json",
            ]
        )
        == 0
    )
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 5
    assert json.loads(lines[-1])["status"] == "completed"
