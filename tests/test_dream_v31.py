from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands import dream as dream_cmd
from harness_mem.commands.dream import (
    dream_auto_tick,
    dream_once,
    dream_status_snapshot,
    latest_dream_ledger,
    undo_dream_item,
)
from harness_mem.commands.doctor import _doctor_dream_status_block
from harness_mem.commands.metabolism_pass import MetabolismPass
from harness_mem.commands.replay_window import ReplayDimension, ReplayWindow
from harness_mem.commands.status import _print_dream_status
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import (
    MemoryEntry,
    Observation,
    ReflectionJob,
    StaleTruthSuggestionCandidate,
)
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


PROJECT = "dream-v31"


def _empty_pass() -> MetabolismPass:
    now = datetime.now(timezone.utc)
    return MetabolismPass(
        window=ReplayWindow(
            time_range=(now - timedelta(days=30), now),
            dimensions={
                "observations": ReplayDimension([], False, 0),
                "pending_candidates": ReplayDimension([], False, 0),
                "historical_truths": ReplayDimension([], False, 0),
                "low_success_skills": ReplayDimension([], False, 0),
                "repeat_search_hits": ReplayDimension([], False, 0),
            },
            signal_ids=[],
            notes=["test-empty-pass"],
        ),
        merge=[],
        stale=[],
        supersede=[],
    )


async def _fake_select_metabolism_pass(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: object,
) -> MetabolismPass:
    return _empty_pass()


def _call_tool(name: str, arguments: dict) -> dict:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    response = handle_request(request)
    assert response is not None
    assert "error" not in response, f"RPC error: {response.get('error')}"
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def _seed_stale_truth(
    backend: LocalMemoryBackend,
    *,
    entry_id: str = "mem-stale",
    candidate_id: str = "stale-candidate",
    evidence_ids: list[str] | None = None,
) -> None:
    created_at = datetime.now(timezone.utc) - timedelta(days=120)
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name=PROJECT,
                category="decision",
                content="Use the old deployment checklist.",
                source="manual",
                created_at=created_at,
                updated_at=created_at,
            )
        )
    )
    run(
        backend.structured_store.save_stale_truth_suggestion_candidate(
            StaleTruthSuggestionCandidate(
                id=candidate_id,
                project_name=PROJECT,
                target_id=entry_id,
                target_kind="memory_entry",
                days_since_last_surface=120,
                evidence_signal_ids=evidence_ids or ["signal-stale"],
                metabolism_run_id="run-stale",
            )
        )
    )


def test_dream_once_handles_stale_candidate_to_terminal_state_without_delete(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)

    dream_run = run(
        dream_once(
            backend,
            project_name=PROJECT,
            config=MergedConfig(),
            source="agent",
        )
    )

    assert dream_run.status == "completed"
    assert dream_run.handling_summary == {
        "processed": 1,
        "applied": 1,
        "rejected": 0,
        "archived": 0,
        "failed": 0,
        "pending_review": 0,
    }
    item = dream_run.items[0]
    assert item.final_action == "applied"
    assert item.proposed_action == "mark_stale"
    assert item.evidence_ids == ["signal-stale"]
    assert item.undo["kind"] == "mark_stale"
    assert item.undo["restore_truth_snapshots"][0]["truth_id"] == "mem-stale"

    candidate = run(
        backend.structured_store.get_stale_truth_suggestion_candidate("stale-candidate")
    )
    assert candidate is not None and candidate.status == "accepted"

    current_entries = run(backend.structured_store.list_memory_entries(PROJECT))
    historical_entries = run(
        backend.structured_store.list_memory_entries(PROJECT, include_history=True)
    )
    assert "mem-stale" not in {entry.id for entry in current_entries}
    historical = {entry.id: entry for entry in historical_entries}
    assert historical["mem-stale"].valid_to is not None
    assert historical["mem-stale"].compacted is False


def test_undo_dream_item_restores_historical_truth_without_primary_key_conflict(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    dream_run = run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))
    item_id = dream_run.items[0].id

    result = run(
        undo_dream_item(
            backend,
            project_name=PROJECT,
            run_id=dream_run.id,
            item_id=item_id,
        )
    )
    assert result["success"] is True
    assert result["status"] == "undone"

    restored = run(backend.structured_store.get_memory_entry("mem-stale"))
    assert restored is not None
    assert restored.valid_to is None
    saved_run = run(backend.structured_store.get_dream_run(dream_run.id))
    assert saved_run is not None
    assert saved_run.items[0].result["undone_at"]

    second = run(
        undo_dream_item(
            backend,
            project_name=PROJECT,
            run_id=dream_run.id,
            item_id=item_id,
        )
    )
    assert second["success"] is True
    assert second["status"] == "already_undone"


def test_dream_once_persists_ledger_before_truth_mutation(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    original_apply_stale = dream_cmd._apply_stale
    observed_status: list[str] = []

    async def checked_apply_stale(*args, **kwargs):
        ledgers = await backend.structured_store.list_dream_runs(PROJECT)
        assert len(ledgers) == 1
        observed_status.append(ledgers[0].status)
        assert ledgers[0].items == []
        return await original_apply_stale(*args, **kwargs)

    monkeypatch.setattr(dream_cmd, "_apply_stale", checked_apply_stale)

    dream_run = run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))

    assert observed_status == ["processing"]
    assert dream_run.status == "completed"
    saved = run(backend.structured_store.get_dream_run(dream_run.id))
    assert saved is not None
    assert saved.status == "completed"
    assert saved.items[0].undo["restore_truth_snapshots"][0]["truth_id"] == "mem-stale"


def test_dream_once_deadline_failure_keeps_ledger_and_truth_unchanged(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)

    with pytest.raises(TimeoutError):
        run(
            dream_once(
                backend,
                project_name=PROJECT,
                config=MergedConfig(),
                deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

    ledgers = run(backend.structured_store.list_dream_runs(PROJECT))
    assert len(ledgers) == 1
    assert ledgers[0].status == "failed"
    assert ledgers[0].items == []
    assert "dream runtime exceeded max_runtime_seconds" in (ledgers[0].notes or [])

    current = run(backend.structured_store.get_memory_entry("mem-stale"))
    candidate = run(
        backend.structured_store.get_stale_truth_suggestion_candidate("stale-candidate")
    )
    assert current is not None and current.valid_to is None
    assert candidate is not None and candidate.status == "pending"


def test_undo_dream_item_reports_failure_without_marking_undone(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    dream_run = run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))
    item_id = dream_run.items[0].id

    backend.structured_store._blob_path("memory_entries", "mem-stale").unlink()

    result = run(
        undo_dream_item(
            backend,
            project_name=PROJECT,
            run_id=dream_run.id,
            item_id=item_id,
        )
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert "restore failed for memory_entry:mem-stale" in result["error"]
    saved_run = run(backend.structured_store.get_dream_run(dream_run.id))
    assert saved_run is not None
    assert "undone_at" not in saved_run.items[0].result


def test_disabled_stale_policy_archives_without_pending_or_truth_mutation(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend, evidence_ids=["signal-policy"])

    run_result = run(
        dream_once(
            backend,
            project_name=PROJECT,
            config={"dream": {"handle": {"allow_mark_stale": False}}},
        )
    )

    assert run_result.handling_summary["processed"] == 1
    assert run_result.handling_summary["archived"] == 1
    assert run_result.handling_summary["pending_review"] == 0
    item = run_result.items[0]
    assert item.final_action == "archived"
    assert item.evidence_ids == ["signal-policy"]
    assert "disabled by dream policy" in item.reason

    current = run(backend.structured_store.get_memory_entry("mem-stale"))
    candidate = run(
        backend.structured_store.get_stale_truth_suggestion_candidate("stale-candidate")
    )
    assert current is not None and current.valid_to is None
    assert candidate is not None and candidate.status == "rejected"


def test_dream_auto_tick_default_off_skips_without_job_or_run(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    payload = run(
        dream_auto_tick(
            backend,
            project_name=PROJECT,
            project_root=str(tmp_path),
            config=MergedConfig(),
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "dream.auto.enabled is false"
    assert backend.reflection_job_store.list(kind="dream") == []
    assert run(backend.structured_store.list_dream_runs(PROJECT)) == []


def test_dream_auto_tick_enabled_creates_dream_job_and_ledger(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-dream-activity",
                session_id="dream-session",
                client="codex",
                raw_content="Recent project activity for the dream scheduler.",
                content_type="transcript",
                metadata={"project_name": PROJECT},
                timestamp=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
        )
    )

    payload = run(
        dream_auto_tick(
            backend,
            project_name=PROJECT,
            project_root=str(tmp_path),
            config=MergedConfig(
                dream_auto_enabled=True,
                dream_auto_trigger="idle",
                dream_auto_idle_seconds=0,
            ),
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "completed"
    jobs = backend.reflection_job_store.list(project_name=PROJECT, kind="dream")
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert jobs[0].phase == "done"
    assert payload["job_id"] == jobs[0].id

    ledger = run(latest_dream_ledger(backend, project_name=PROJECT))
    assert ledger["success"] is True
    assert ledger["run"]["id"] == payload["run_id"]
    assert ledger["run"]["reflection_job_id"] == jobs[0].id


def test_dream_auto_tick_skips_when_dream_job_is_already_processing(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-dream-active-job",
                session_id="dream-active-session",
                client="codex",
                raw_content="Recent project activity while a dream job is processing.",
                content_type="transcript",
                metadata={"project_name": PROJECT},
                timestamp=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
        )
    )
    active = ReflectionJob(
        project_name=PROJECT,
        project_root=str(tmp_path),
        kind="dream",
        phase="metabolism",
        status="processing",
        source="scheduler",
    )
    backend.reflection_job_store.save(active)

    payload = run(
        dream_auto_tick(
            backend,
            project_name=PROJECT,
            project_root=str(tmp_path),
            config=MergedConfig(
                dream_auto_enabled=True,
                dream_auto_trigger="idle",
                dream_auto_idle_seconds=0,
            ),
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "dream job already processing"
    assert payload["job_id"] == active.id
    assert len(backend.reflection_job_store.list(project_name=PROJECT, kind="dream")) == 1
    assert run(backend.structured_store.list_dream_runs(PROJECT)) == []


def test_mcp_dream_run_ledger_and_undo_item(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    set_backend_override(backend)
    try:
        run_data = _call_tool(
            "dream_run",
            {"project_name": PROJECT, "project_root": str(tmp_path)},
        )
        assert run_data["success"] is True
        dream_run = run_data["run"]
        assert dream_run["handling_summary"]["processed"] == 1
        assert dream_run["handling_summary"]["pending_review"] == 0
        assert run_data["maintenance_summary"]["auto_applied"] is True
        assert run_data["maintenance_summary"]["undo_available"] is True
        assert run_data["candidate_counts"]["applied"] == 1
        item = dream_run["items"][0]
        assert item["final_action"] == "applied"

        ledger = _call_tool("dream_ledger", {"project_name": PROJECT})
        assert ledger["success"] is True
        assert ledger["run"]["id"] == dream_run["id"]
        assert ledger["maintenance_summary"]["auto_applied"] is True

        undone = _call_tool(
            "undo_dream_item",
            {
                "project_name": PROJECT,
                "run_id": dream_run["id"],
                "item_id": item["id"],
            },
        )
        assert undone["success"] is True
        assert undone["status"] == "undone"
        assert undone["maintenance_summary"]["undo_available"] is False
    finally:
        set_backend_override(None)

    restored = run(backend.structured_store.get_memory_entry("mem-stale"))
    assert restored is not None and restored.valid_to is None


def test_mcp_dream_auto_tick_enabled_creates_dream_job(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    (tmp_path / ".harness-mem.toml").write_text(
        "[dream.auto]\n"
        "enabled = true\n"
        'trigger = "idle"\n'
        "idle_seconds = 0\n",
        encoding="utf-8",
    )
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-mcp-dream-activity",
                session_id="dream-mcp-session",
                client="codex",
                raw_content="MCP dream auto tick has project activity.",
                content_type="transcript",
                metadata={"project_name": PROJECT},
                timestamp=datetime.now(timezone.utc) - timedelta(seconds=5),
            )
        )
    )
    set_backend_override(backend)
    try:
        payload = _call_tool(
            "dream_auto_tick",
            {"project_name": PROJECT, "project_root": str(tmp_path)},
        )
    finally:
        set_backend_override(None)

    assert payload["success"] is True
    assert payload["status"] == "completed"
    jobs = backend.reflection_job_store.list(project_name=PROJECT, kind="dream")
    assert len(jobs) == 1
    assert jobs[0].id == payload["job_id"]


def test_dream_status_snapshot_reports_last_run_and_scheduler_reason(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    dream_run = run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))

    snapshot = run(
        dream_status_snapshot(
            backend,
            project_name=PROJECT,
            config=MergedConfig(dream_auto_enabled=True),
        )
    )

    assert snapshot["enabled"] is True
    assert snapshot["last_run_id"] == dream_run.id
    assert snapshot["last_processed"] == 1
    assert snapshot["last_failed"] == 0
    assert snapshot["scheduler_eligible"] is False
    assert snapshot["scheduler_reason"] in {
        "no project activity to dream over",
        "no new project activity since the last dream run",
    }


def test_status_output_includes_dream_auto_and_last_dream(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))

    run(_print_dream_status(backend, PROJECT))

    output = capsys.readouterr().out
    assert "Dream auto:" in output
    assert "Last dream: completed (processed 1, failed 0)" in output


def test_doctor_output_includes_dream_scheduler_visibility(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(dream_cmd, "select_metabolism_pass", _fake_select_metabolism_pass)
    _seed_stale_truth(backend)
    run(dream_once(backend, project_name=PROJECT, config=MergedConfig()))
    snapshot = run(
        dream_status_snapshot(
            backend,
            project_name=PROJECT,
            config=MergedConfig(dream_auto_enabled=True),
        )
    )

    _doctor_dream_status_block(snapshot)

    output = capsys.readouterr().out
    assert "Dream auto maintenance:" in output
    assert "  enabled: enabled" in output
    assert "  last run: completed (processed 1, failed 0)" in output
    assert "  scheduler: not eligible" in output


def test_dream_run_payload_has_no_pending_review_terminal_action() -> None:
    from harness_mem.core.schemas import DreamItem, DreamRun

    run_payload = DreamRun(
        project_name=PROJECT,
        items=[
            DreamItem(
                source_kind="stale_truth_suggestion",
                source_id="candidate",
                proposed_action="mark_stale",
                final_action="archived",
                reason="policy archived it",
            )
        ],
    ).to_dict()

    assert run_payload["handling_summary"]["pending_review"] == 0
    assert {item["final_action"] for item in run_payload["items"]} <= {
        "applied",
        "rejected",
        "archived",
        "failed",
    }
    assert "pending_review" not in json.dumps(run_payload["items"])
