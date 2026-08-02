from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.distill_lifecycle import (
    _coarse_drain_estimate,
    build_distill_maintenance_offer,
    distill_drainer_metrics,
    pending_distill_jobs,
    render_pending_distill_instruction,
    stage_distill_job,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


def test_distill_job_is_deduplicated_and_rendered(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        first = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-1", "obs-2"],
            source="ide_hook",
        )
        second = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-2", "obs-1"],
            source="ide_hook",
        )

        assert first is not None
        assert second is not None
        assert second.id == first.id
        assert pending_distill_jobs(backend, project_name="demo") == []
        assert render_pending_distill_instruction([]) == ""
        empty_offer = build_distill_maintenance_offer([])
        assert empty_offer["agent_execution_required"] is False
        assert empty_offer["process_limit"] == 0
        assert empty_offer["job_ids"] == []
        assert empty_offer["instruction"] == ""
    finally:
        _run(backend.close())


def test_agent_active_drainer_enforces_daily_new_job_budget(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        for index in range(3):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"session-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        timestamp=now,
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )

        first = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            daily_job_budget=1,
            now=now,
        )
        second = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            daily_job_budget=1,
            now=now,
        )
        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=1,
            now=now,
        )
        instruction = render_pending_distill_instruction(first, metrics=metrics)
        offer = build_distill_maintenance_offer(
            first,
            max_jobs=1,
            metrics=metrics,
        )

        assert len(first) == 1
        assert [job.id for job in second] == [job.id for job in first]
        assert metrics["active"] == 2
        assert metrics["parked"] == 1
        assert metrics["offered_today"] == 1
        assert metrics["daily_budget_remaining"] == 0
        assert metrics["state"] == "waiting_for_agent"
        assert metrics["background_semantic_processing"] is False
        assert "State: waiting_for_agent" in instruction
        assert "three recent jobs, then one oldest" in instruction
        assert f"process up to 1 now: {first[0].id}" in instruction
        assert "distill_job_id=<selected id>" in instruction
        assert "run_ingest=false" in instruction
        assert offer["contract_version"] == "agent-distill-offer-v1"
        assert offer["agent_execution_required"] is True
        assert offer["job_ids"] == [first[0].id]
        assert offer["process_limit"] == 1
        assert offer["prepare_arguments"] == {
            "run_ingest": False,
            "evidence_mode": "semantic",
            "detail_level": "compact",
            "budget_tokens": 3000,
        }
        assert offer["failure_policy"] == "defer_and_continue"
    finally:
        _run(backend.close())


def test_agent_active_drainer_only_charges_jobs_emitted_to_agent(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        for index in range(3):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"session-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        timestamp=now,
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )

        offered = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=3,
            max_jobs=1,
            daily_job_budget=3,
            now=now,
        )
        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=3,
            now=now,
        )

        assert len(offered) == 1
        assert metrics["active"] == 3
        assert metrics["offered_today"] == 1
        assert metrics["daily_budget_remaining"] == 2
    finally:
        _run(backend.close())


def test_drainer_reports_backoff_and_zero_throughput_without_background_claims(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        result = _run(
            persist_session_snapshot(
                backend,
                Observation(
                    session_id="failed-session",
                    client="codex",
                    raw_content="User: inspect failure\n\nAssistant: blocked",
                    content_type="transcript",
                    metadata={},
                ),
                project_name="demo",
                project_root=str(tmp_path),
                client="codex",
                session_id="failed-session",
                source_kind="jsonl",
                source_uri="file:///failed-session.jsonl",
                source_text="failed source",
            )
        )
        assert result.distill_job_id is not None
        backend.transcript_store.claim_distill_chunks(
            result.distill_job_id,
            lease_owner="broken-agent",
        )
        backend.transcript_store.defer_distill_job(
            result.distill_job_id,
            error="parser failed",
        )

        metrics = distill_drainer_metrics(backend, project_name="demo")
        reasons = {reason["code"]: reason for reason in metrics["stuck_reasons"]}

        assert metrics["state"] == "backoff"
        assert metrics["pending_total"] == 1
        assert reasons["retry_backoff"]["retry_after"]
        assert reasons["zero_7d_throughput"]["count"] == 1
        assert metrics["drain_estimate"]["status"] == "unavailable"
        assert metrics["drain_estimate"]["reason"] == "zero_7d_throughput"
        assert metrics["drain_estimate"]["background_semantic_processing"] is False
        assert metrics["agent_required"] is True
    finally:
        _run(backend.close())


def test_drainer_estimate_accounts_for_exhausted_daily_budget(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime.now(timezone.utc)
    try:
        job_ids = []
        for index in range(2):
            result = _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"budget-session-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"budget-session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///budget-session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )
            assert result.distill_job_id is not None
            job_ids.append(result.distill_job_id)

        offered = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=1,
            max_jobs=1,
            daily_job_budget=1,
            now=now,
        )
        assert len(offered) == 1
        completed_id = offered[0].id
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            completed_id,
            lease_owner="agent",
            limit=20,
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                completed_id,
                chunk.id,
                lease_owner="agent",
                result={"summary": "done"},
            )
        backend.transcript_store.finalize_distill_job(
            completed_id,
            semantic_review={
                "final_user_request": "request",
                "final_outcome": "complete",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
            },
        )
        backend.transcript_store.record_distill_completion_outcome(
            completed_id,
            disposition="no_candidate",
            reason_codes=["no_durable_candidate"],
            promotion_summary={
                "suggested": 0,
                "promoted": 0,
                "rejected": 0,
                "evidence_admission": {
                    "repository_verified": 2,
                    "user_stated": 1,
                    "unverified_blocked": 3,
                    "contradicted": 1,
                },
            },
            source_cleanup_status="retained",
        )
        pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=1,
            max_jobs=1,
            daily_job_budget=1,
            now=now,
        )

        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=1,
            now=now,
        )
        reason_codes = {reason["code"] for reason in metrics["stuck_reasons"]}

        assert metrics["state"] == "daily_budget_exhausted"
        assert metrics["pending_total"] == 1
        assert metrics["completed_7d"] == 1
        assert metrics["promoted_7d"] == 0
        assert metrics["no_candidate_7d"] == 1
        assert metrics["legacy_unknown_7d"] == 0
        assert metrics["evidence_admission_7d"] == {
            "repository_verified": 2,
            "user_stated": 1,
            "unverified_blocked": 3,
            "contradicted": 1,
            "legacy_or_unknown": 0,
        }
        assert "daily_budget_exhausted" in reason_codes
        assert metrics["drain_estimate"]["status"] == "coarse_estimate"
        assert metrics["drain_estimate"]["starts_after"].endswith("T00:00:00+00:00")
        assert metrics["drain_estimate"]["estimated_calendar_days"] >= 2
        assert metrics["drain_estimate"]["requires_agent_execution"] is True
    finally:
        _run(backend.close())


def test_drainer_estimate_includes_latest_retry_backoff() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    estimate = _coarse_drain_estimate(
        pending_total=2,
        active=1,
        parked=0,
        retry_backoff_count=1,
        throughput_per_day=2.0,
        daily_job_budget=3,
        daily_budget_remaining=3,
        state="backoff",
        retry_backoff=[SimpleNamespace(retry_after=now + timedelta(days=10))],
        current=now,
    )

    assert estimate["status"] == "coarse_estimate"
    assert estimate["estimated_calendar_days"] == 11
    assert estimate["latest_retry_after"] == "2026-08-05T12:00:00+00:00"
    assert "latest retry backoff" in estimate["basis"]


def test_auto_review_completes_distill_job_then_runs_dream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.distill-lifecycle"),
    )
    try:
        job = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-1"],
            source="agent",
        )
        assert job is not None
        job.status = "processing"
        backend.reflection_job_store.save(job)

        async def fake_dream(*_args, **_kwargs):
            return {"success": True, "status": "completed", "job_id": "dream-1"}

        monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
        payload = tool_handlers.tool_auto_review_candidates("demo", apply=True)

        assert payload["distill_jobs_completed"] == [job.id]
        assert payload["dream"]["job_id"] == "dream-1"
        reloaded = backend.reflection_job_store.get(job.id)
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.phase == "done"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        _run(backend.close())
