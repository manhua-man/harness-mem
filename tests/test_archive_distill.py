from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands.archive_distill import (
    inventory_codex_archives,
    run_archive_distill_batch,
)
from harness_mem.config.merge import load_merged_config


def _write_archive(root: Path, workspace: Path, session_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-{session_id}.jsonl"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(workspace),
                "timestamp": "2026-08-13T00:00:00Z",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "turn_id": "turn-1",
                "type": "user_message",
                "message": "Always run the related tests for small changes.",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Understood."}],
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(root: Path, *, enabled: bool) -> None:
    root.joinpath(".harness-mem.toml").write_text(
        "[archive_distill]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        "batch_size = 3\n"
        "daily_limit = 20\n"
        "order = \"oldest_first\"\n"
        "project_scope = \"detected\"\n"
        "unresolved_project = \"defer\"\n"
        "require_answer_packet = true\n"
        "report_promotions = true\n"
        "warn_tokens = 15000\n"
        "warn_seconds = 40\n",
        encoding="utf-8",
    )


def test_archive_inventory_detects_projects_and_defers_unresolved(tmp_path: Path) -> None:
    control = tmp_path / "control"
    project_a = tmp_path / "project-a"
    control.mkdir()
    project_a.mkdir()
    archive = tmp_path / "archives"
    _write_archive(archive, project_a, "session-a")
    missing = tmp_path / "missing"
    _write_archive(archive, missing, "session-missing")

    inventory = inventory_codex_archives(
        control_root=control,
        config=load_merged_config(control),
        archive_dir=archive,
    )

    assert inventory["sessions_found"] == 2
    assert inventory["eligible"] == 1
    assert inventory["unresolved"] == 1
    assert inventory["eligible_sessions"][0]["project_root"] == str(project_a)


def test_archive_dry_run_does_not_require_enabled_or_write_ledger(tmp_path: Path) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    archive = tmp_path / "archives"
    _write_archive(archive, project, "session-a")

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=tmp_path / "data",
        )
    )

    assert result["success"] is True
    assert result["enabled"] is False
    assert [item["session_id"] for item in result["selected"]] == ["session-a"]
    assert not (tmp_path / "data" / "archive_distill").exists()
    assert result["policy"]["allowed_project_roots"] == []


def test_archive_dry_run_reports_bounded_unresolved_policy(tmp_path: Path) -> None:
    control = tmp_path / "control"
    control.mkdir()
    missing = tmp_path / "missing-project"
    archive = tmp_path / "archives"
    _write_archive(archive, missing, "session-missing")

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=tmp_path / "data",
        )
    )

    assert result["unresolved_resolution"] == {"count": 1, "action": "defer"}


def test_archive_apply_requires_explicit_enable(tmp_path: Path) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    archive = tmp_path / "archives"
    _write_archive(archive, project, "session-a")

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
        )
    )

    assert result["success"] is False
    assert result["error"] == "archive_distill is disabled"


def test_archive_apply_reports_persisted_answer_packet_and_daily_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    _write_config(control, enabled=True)
    project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = true\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    _write_archive(archive, project, "session-a")

    def fake_batch(backend, **kwargs):
        job_id = kwargs["preferred_job_id"]
        job = backend.transcript_store.get_distill_job(job_id)
        assert job is not None
        lease_owner = "archive-test"
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            job.id, lease_owner=lease_owner, limit=100
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                job.id,
                chunk.id,
                lease_owner=lease_owner,
                result={"summary": "read"},
            )
        backend.transcript_store.finalize_distill_job(
            job.id,
            semantic_review={
                "session_summary": "The user defined a durable related-test rule.",
                "final_user_request": "Always run related tests for small changes.",
                "final_outcome": "The rule was accepted.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "promote",
            },
            output_candidate_ids=[],
        )
        packet = {
            "answer_status": "ANSWERED",
            "question": "Is the test rule supported?",
            "core_conclusion": "Small changes require related tests.",
            "evidence_basis": ["user_statement"],
            "verified_at": "2026-08-13T00:00:00+00:00",
            "promotion_status": "promoted",
            "promoted_items": [
                {
                    "title": "Related test rule",
                    "fact": "Small changes require related tests.",
                    "kind": "rule",
                    "category": "testing",
                }
            ],
            "destination_project": job.project_name,
            "knowledge_kind": ["rule"],
            "knowledge_category": ["testing"],
        }
        backend.transcript_store.record_distill_completion_outcome(
            job.id,
            disposition="promoted",
            reason_codes=["durable_memory_promoted"],
            promotion_summary={"promoted": 1, "answer_packet": packet},
            source_cleanup_status="deleted",
        )
        return {
            "success": True,
            "state": "succeeded",
            "outcomes": [
                {
                    "job_id": job.id,
                    "session_id": job.session_id,
                    "status": "completed",
                    "note": {"path": str(tmp_path / "note.md")},
                    "provider": {"total_tokens": 1000, "duration_seconds": 2.5},
                }
            ],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        fake_batch,
    )
    now = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
            now=now,
        )
    )

    assert result["success"] is True
    assert result["completed"] == 1
    outcome = result["outcomes"][0]
    assert outcome["answer_packet"]["answer_status"] == "ANSWERED"
    assert outcome["promoted_items"][0]["fact"] == "Small changes require related tests."
    assert outcome["warnings"] == []
    ledger = json.loads(Path(result["ledger"]).read_text(encoding="utf-8"))
    assert ledger["processed_session_ids"] == ["session-a"]

    repeated = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
            now=now,
        )
    )
    assert repeated["selected"] == []
    assert repeated["outcomes"] == []


def test_archive_apply_verify_emits_run_bound_direct_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    _write_config(control, enabled=True)
    project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = true\n"
        "[distill]\ndelete_source_after_complete = false\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    _write_archive(archive, project, "session-verify")

    def fake_batch(backend, **kwargs):
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
        assert job is not None
        lease_owner = "archive-verify"
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            job.id, lease_owner=lease_owner, limit=100
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                job.id,
                chunk.id,
                lease_owner=lease_owner,
                result={"summary": "read"},
            )
        backend.transcript_store.finalize_distill_job(
            job.id,
            semantic_review={
                "session_summary": "The session contains no durable reusable knowledge.",
                "final_user_request": "Run one transient check.",
                "final_outcome": "The transient check completed.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "not_applicable",
                "promotion_decision": "no_promotion",
            },
        )
        packet = {
            "answer_status": "NOT_APPLICABLE",
            "question": "Run one transient check.",
            "core_conclusion": "No durable knowledge was produced.",
            "evidence_basis": [],
            "evaluated_at": "2026-08-13T00:00:00Z",
            "verified_at": None,
            "promotion_status": "not_promoted",
            "promoted_items": [],
            "destination_project": job.project_name,
            "knowledge_kind": [],
            "knowledge_category": [],
        }
        stored = backend.transcript_store.record_distill_completion_outcome(
            job.id,
            disposition="no_candidate",
            reason_codes=["no_durable_candidate"],
            promotion_summary={"promoted": 0, "answer_packet": packet},
            source_cleanup_status="retained",
        )
        from harness_mem.session_notes import materialize_session_note

        note = materialize_session_note(stored, notes_dir=tmp_path / "notes")
        return {
            "success": True,
            "state": "succeeded",
            "outcomes": [
                {
                    "job_id": job.id,
                    "session_id": job.session_id,
                    "status": "completed",
                    "note": note,
                    "provider": {"total_tokens": 0, "duration_seconds": 0.0},
                }
            ],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        fake_batch,
    )
    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
        )
    )

    assert result["verification"]["status"] == "passed"
    verified = result["verification"]["outcomes"][0]
    assert verified["checks"]["answer_packet_persisted"] is True
    assert verified["checks"]["note_session_binding_valid"] is True
    assert verified["retrieval"] == {
        "status": "not_applicable",
        "reason": "no_promoted_items",
        "items": [],
    }
    assert Path(result["run_receipt"]).is_file()


def test_trivial_archive_request_is_classified_without_model(tmp_path: Path) -> None:
    from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
    from harness_mem.commands.archive_distill import _trivial_archive_request

    archive = tmp_path / "archives"
    source = _write_archive(archive, tmp_path, "smoke")
    records = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
    ]
    records[1]["payload"]["message"] = "Return exactly: ARCHIVE_SMOKE_OK"
    records[2]["payload"]["content"][0]["text"] = "ARCHIVE_SMOKE_OK"
    records.extend(
        [
            {
                "type": "response_item",
                "payload": {
                    "turn_id": "hook-turn",
                    "type": "function_call",
                    "name": "harness_mem_hook",
                    "arguments": "{}",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "turn_id": "hook-turn",
                    "type": "agent_message",
                    "phase": "commentary",
                    "message": "Automatic maintenance ran.",
                },
            },
        ]
    )
    source.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )

    assert _trivial_archive_request(
        CodexArchiveAdapter(None, archive_dir=archive),
        source,
    ) == "Return exactly: ARCHIVE_SMOKE_OK"


def test_trivial_archive_request_rejects_second_user_intent(tmp_path: Path) -> None:
    from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
    from harness_mem.commands.archive_distill import _trivial_archive_request

    archive = tmp_path / "archives"
    source = _write_archive(archive, tmp_path, "not-smoke")
    records = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
    ]
    records[1]["payload"]["message"] = "Return exactly: FIRST_OK"
    records.append(
        {
            "type": "event_msg",
            "payload": {
                "turn_id": "turn-2",
                "type": "user_message",
                "message": "Now inspect the repository and fix the bug.",
            },
        }
    )
    source.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )

    assert _trivial_archive_request(
        CodexArchiveAdapter(None, archive_dir=archive),
        source,
    ) is None


def test_trivial_archive_apply_uses_zero_token_canonical_path(tmp_path: Path) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    _write_config(control, enabled=True)
    project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = true\n"
        "[distill]\ndelete_source_after_complete = false\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    source = _write_archive(archive, project, "smoke-real")
    records = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
    ]
    records[1]["payload"]["message"] = "Return exactly: ARCHIVE_SMOKE_OK"
    records[2]["payload"]["content"][0]["text"] = "ARCHIVE_SMOKE_OK"
    source.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
            notes_dir=tmp_path / "notes",
        )
    )

    assert result["success"] is True
    assert result["outcomes"][0]["classification"] == "trivial_smoke"
    assert result["outcomes"][0]["provider"]["total_tokens"] == 0
    assert result["outcomes"][0]["answer_packet"]["evaluated_at"]
    assert result["outcomes"][0]["answer_packet"]["verified_at"] is None
    assert result["verification"]["status"] == "passed"


def test_waiting_review_job_does_not_block_archive_batch(tmp_path: Path) -> None:
    from harness_mem.commands.archive_distill import _active_distill_worker_jobs
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        source = _write_archive(tmp_path / "archives", tmp_path, "waiting-review")
        adapter = __import__(
            "harness_mem.adapters.codex.archive_adapter",
            fromlist=["CodexArchiveAdapter"],
        ).CodexArchiveAdapter(backend, archive_dir=source.parent)
        synced = asyncio.run(
            adapter.sync_session(
                source,
                "waiting-review",
                "demo",
                project_root=tmp_path,
            )
        )
        lease_owner = "chunk-reader"
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            synced.distill_job_id,
            lease_owner=lease_owner,
            limit=100,
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                synced.distill_job_id,
                chunk.id,
                lease_owner=lease_owner,
                result={"summary": "read"},
            )
        backend.transcript_store.reconcile_distill_jobs(project_name="demo")
        waiting = backend.transcript_store.get_distill_job(synced.distill_job_id)
        assert waiting.status == "reviewing"
        assert waiting.review_lease_owner is None

        assert _active_distill_worker_jobs(
            backend,
            project_name="demo",
        ) == []
    finally:
        asyncio.run(backend.close())


def test_archive_apply_releases_lock_when_backend_init_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness_mem.maintenance_lock import maintenance_is_locked

    control = tmp_path / "control"
    control.mkdir()
    _write_config(control, enabled=True)
    data_dir = tmp_path / "data"

    async def fail_init(_backend) -> None:
        raise RuntimeError("init failed")

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.LocalMemoryBackend.init",
        fail_init,
    )

    with pytest.raises(RuntimeError, match="init failed"):
        asyncio.run(
            run_archive_distill_batch(
                control_root=control,
                apply=True,
                archive_dir=tmp_path / "archives",
                data_dir=data_dir,
            )
        )

    assert maintenance_is_locked(data_dir) is False
