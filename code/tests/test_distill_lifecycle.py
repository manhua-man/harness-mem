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
        assert empty_offer["distill_job_id"] is None
        assert empty_offer["jobs"] == []
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
        assert offer["contract_version"] == "agent-distill-offer-v2"
        assert offer["agent_execution_required"] is True
        assert offer["job_ids"] == [first[0].id]
        assert offer["process_limit"] == 1
        assert offer["distill_job_id"] == first[0].id
        assert offer["execution_order"] == "sequential"
        assert offer["prepare_arguments"] == {
            "run_ingest": False,
            "evidence_mode": "semantic",
            "detail_level": "compact",
            "budget_tokens": 3000,
        }
        assert offer["failure_policy"] == "defer_and_continue"
        assert offer["per_job_failure_policy"] == {
            "on_failure": "defer_job",
            "on_owned_failure": "defer_job",
            "on_busy": "skip_without_defer",
            "on_completed_finalize_retry": "replay_finalize",
            "continue_with_next": True,
        }
        assert offer["budget"] == {
            "scope": "complete_serialized_responses",
            "per_job_target_tokens": 3000,
            "maximum_jobs": 1,
            "maximum_target_tokens": 3000,
        }
        assert offer["jobs"][0]["distill_job_id"] == first[0].id
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


def test_status_queue_preview_is_bounded_readable_and_hides_internal_ids(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        created_jobs = []
        for index in range(2):
            result = _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"visible-session-{index}",
                        client="codex-archive",
                        raw_content=f"User: private request {index}\nAssistant: done",
                        content_type="transcript",
                        timestamp=now + timedelta(seconds=index),
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex-archive",
                    session_id=f"visible-session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///visible-session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )
            assert result.distill_job_id is not None
            created_jobs.append(result.distill_job_id)

        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=0,
            now=now,
        )

        assert metrics["state"] == "daily_budget_exhausted"
        assert len(metrics["queue_preview"]) == 2
        row = metrics["queue_preview"][0]
        assert row["project_name"] == "demo"
        assert row["source_host"] == "codex-archive"
        assert row["session_label"].startswith("Codex archive session captured ")
        assert row["state"] == "waiting_for_daily_budget"
        assert row["handler"] == {
            "kind": "waiting",
            "label": "no Agent is running; waiting for the next daily budget",
        }
        serialized = str(metrics["queue_preview"])
        assert "visible-session-" not in serialized
        assert not any(job_id in serialized for job_id in created_jobs)
        assert "private request" not in serialized
    finally:
        _run(backend.close())


def test_status_queue_preview_identifies_an_active_autonomous_worker(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        result = _run(
            persist_session_snapshot(
                backend,
                Observation(
                    session_id="autonomous-visible-session",
                    client="codex",
                    raw_content="User: process this\nAssistant: working",
                    content_type="transcript",
                    metadata={},
                ),
                project_name="demo",
                project_root=str(tmp_path),
                client="codex",
                session_id="autonomous-visible-session",
                source_kind="jsonl",
                source_uri="file:///autonomous-visible-session.jsonl",
                source_text="source",
            )
        )
        assert result.distill_job_id is not None
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            result.distill_job_id,
            lease_owner="autonomous:42:test",
            limit=100,
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                result.distill_job_id,
                chunk.id,
                lease_owner="autonomous:42:test",
                result={"inspected": True},
            )
        claimed = backend.transcript_store.claim_distill_review(
            result.distill_job_id,
            lease_owner="autonomous:42:test",
            execution_source="autonomous_worker",
        )
        assert claimed is not None

        metrics = distill_drainer_metrics(backend, project_name="demo")

        assert len(metrics["queue_preview"]) == 1
        row = metrics["queue_preview"][0]
        assert row["project_name"] == "demo"
        assert row["session_label"].startswith("Codex session captured ")
        assert row["source_host"] == "codex"
        assert row["state"] == "reviewing_session"
        assert row["progress"] == {"completed_chunks": 1, "expected_chunks": 1}
        assert row["handler"] == {
            "kind": "autonomous_worker",
            "label": "harness-mem autonomous distill worker",
        }
        assert "autonomous-visible-session" not in str(row)
        assert result.distill_job_id not in str(row)
    finally:
        _run(backend.close())


def test_bounded_batch_covers_backlog_sizes_caps_and_repeated_offers(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        assert pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=4,
            max_jobs=99,
            record_offer=False,
            now=now,
        ) == []

        for count in range(1, 5):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"batch-session-{count}",
                        client="codex",
                        raw_content=f"User: request {count}\n\nAssistant: done {count}",
                        content_type="transcript",
                        timestamp=now + timedelta(seconds=count),
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"batch-session-{count}",
                    source_kind="jsonl",
                    source_uri=f"file:///batch-session-{count}.jsonl",
                    source_text=f"source {count}",
                )
            )
            preview = pending_distill_jobs(
                backend,
                project_name="demo",
                target_backlog=4,
                max_jobs=99,
                daily_job_budget=8,
                record_offer=False,
                now=now,
            )
            assert len(preview) == min(count, 3)

        first_offer = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=4,
            max_jobs=3,
            daily_job_budget=2,
            now=now,
        )
        repeated_offer = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=4,
            max_jobs=3,
            daily_job_budget=2,
            now=now,
        )
        assert len(first_offer) == 2
        assert [job.id for job in repeated_offer] == [job.id for job in first_offer]
        assert distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=2,
            now=now,
        )["offered_today"] == 2

        explicit_offer = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=4,
            max_jobs=3,
            daily_job_budget=3,
            now=now + timedelta(days=1),
        )
        contract = build_distill_maintenance_offer(
            explicit_offer,
            max_jobs=99,
            budget_tokens=6400,
        )
        assert len(explicit_offer) == 3
        assert build_distill_maintenance_offer(explicit_offer)["process_limit"] == 2
        assert contract["process_limit"] == 3
        assert contract["job_ids"] == [job.id for job in explicit_offer]
        assert contract["distill_job_id"] == explicit_offer[0].id
        assert contract["prepare_arguments"]["budget_tokens"] == 6400
        assert contract["budget"] == {
            "scope": "complete_serialized_responses",
            "per_job_target_tokens": 6400,
            "maximum_jobs": 3,
            "maximum_target_tokens": 19200,
        }
        assert [item["ordinal"] for item in contract["jobs"]] == [1, 2, 3]
        assert all(
            item["failure_policy"]["continue_with_next"]
            for item in contract["jobs"]
        )
        assert "budget_tokens=6400" in contract["instruction"]
    finally:
        _run(backend.close())


def test_thirty_two_session_burst_drains_in_sixteen_two_job_opportunities(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
    review = {
        "final_user_request": "capture the completed task",
        "final_outcome": "no durable candidate",
        "last_turn_status": "answered",
        "contradictions": [],
        "unfinished_work": [],
        "evidence_status": "answered",
        "promotion_decision": "no_promotion",
    }
    try:
        for index in range(32):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"burst-{index:02d}",
                        client="codex",
                        raw_content=f"User: task {index}\nAssistant: done",
                        content_type="transcript",
                        timestamp=now + timedelta(seconds=index),
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"burst-{index:02d}",
                    source_kind="jsonl",
                    source_uri=f"file:///burst-{index:02d}.jsonl",
                    source_text=f"source {index}\n",
                )
            )

        completed: list[str] = []
        for opportunity in range(16):
            offered = pending_distill_jobs(
                backend,
                project_name="demo",
                target_backlog=2,
                max_jobs=2,
                daily_job_budget=32,
                now=now,
            )
            assert len(offered) == 2, opportunity
            for job in offered:
                for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
                    job.id,
                    lease_owner=f"burst-agent-{opportunity}",
                    limit=100,
                ):
                    backend.transcript_store.checkpoint_distill_chunk(
                        job.id,
                        chunk.id,
                        lease_owner=f"burst-agent-{opportunity}",
                        result={"inspected": True},
                    )
                backend.transcript_store.finalize_distill_job(
                    job.id,
                    semantic_review=review,
                    output_candidate_ids=[],
                )
                backend.transcript_store.record_distill_completion_outcome(
                    job.id,
                    disposition="no_candidate",
                    reason_codes=["no_durable_candidate"],
                    promotion_summary={"promoted": 0},
                    source_cleanup_status="retained",
                )
                completed.append(job.id)

        assert len(set(completed)) == 32
        assert pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            max_jobs=2,
            daily_job_budget=32,
            now=now,
        ) == []
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
