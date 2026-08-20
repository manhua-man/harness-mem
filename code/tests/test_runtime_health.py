from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.runtime_health import runtime_health_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


def test_retrieval_quality_scorecard_is_project_isolated_and_marks_no_feedback(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        _run(
            backend.structured_store.save_retrieval_signal(
                RetrievalSignal(
                    project_name="demo",
                    signal_type="search_hit",
                    target_kind="memory_entry",
                    target_id="entry-1",
                )
            )
        )
        for signal_type, value, reason in (
            ("retrieval_abstained", 2.0, "insufficient_context"),
            ("retrieval_excluded", 3.0, "historical"),
            ("retrieval_excluded", 2.0, "temporal_conflict"),
        ):
            _run(
                backend.structured_store.save_retrieval_signal(
                    RetrievalSignal(
                        project_name="demo",
                        signal_type=signal_type,
                        target_kind="context_source",
                        target_id=f"quality-{signal_type}-{reason}",
                        value=value,
                        context={"reason": reason},
                    )
                )
            )
        _run(
            backend.structured_store.save_retrieval_signal(
                RetrievalSignal(
                    project_name="other",
                    signal_type="context_outcome",
                    target_kind="context_source",
                    target_id="entry-1",
                    context={"outcome": "misleading"},
                )
            )
        )
        _run(
            backend.structured_store.save_retrieval_signal(
                RetrievalSignal(
                    project_name="demo",
                    signal_type="context_outcome",
                    target_kind="context_source",
                    target_id="orphan-entry",
                    context={
                        "outcome": "used",
                        "retrieval_id": "orphan-retrieval",
                    },
                )
            )
        )

        report = _run(
            runtime_health_report(
                backend,
                data_dir=backend.data_dir,
                project_name="demo",
            )
        )
        scorecard = report["retrieval_health"]["quality_scorecard"]

        assert scorecard["project_name"] == "demo"
        assert scorecard["surfaced"] == 1
        assert scorecard["abstained"] == 2
        assert scorecard["stale_excluded"] == 3
        assert scorecard["conflict_excluded"] == 2
        assert scorecard["excluded_total"] == 5
        assert scorecard["used"] == 0
        assert scorecard["ignored"] == 0
        assert scorecard["misleading"] == 0
        assert scorecard["orphan_feedback"] == 1
        assert scorecard["feedback_total"] == 0
        assert scorecard["insufficient_feedback"] is True
        assert scorecard["assessment"] == "insufficient_feedback"
    finally:
        _run(backend.close())


def test_retrieval_quality_scorecard_distinguishes_poor_feedback(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        for outcome in ("used", "ignored", "misleading"):
            retrieval_id = f"retrieval-{outcome}"
            target_id = f"entry-{outcome}"
            _run(
                backend.structured_store.save_retrieval_signal(
                    RetrievalSignal(
                        project_name="demo",
                        signal_type="search_hit",
                        target_kind="memory_entry",
                        target_id=target_id,
                        context={"retrieval_id": retrieval_id},
                    )
                )
            )
            _run(
                backend.structured_store.save_retrieval_signal(
                    RetrievalSignal(
                        project_name="demo",
                        signal_type="context_outcome",
                        target_kind="context_source",
                        target_id=target_id,
                        context={
                            "outcome": outcome,
                            "retrieval_id": retrieval_id,
                        },
                    )
                )
            )

        report = _run(
            runtime_health_report(
                backend,
                data_dir=backend.data_dir,
                project_name="demo",
            )
        )
        scorecard = report["retrieval_health"]["quality_scorecard"]

        assert scorecard["feedback_total"] == 3
        assert scorecard["insufficient_feedback"] is False
        assert scorecard["assessment"] == "poor_feedback"
        assert scorecard["used"] == 1
        assert scorecard["ignored"] == 1
        assert scorecard["misleading"] == 1
    finally:
        _run(backend.close())


def test_memory_funnel_correlates_distinct_retrievals_and_marks_legacy_missing(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        signals = [
            RetrievalSignal(
                project_name="demo",
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id="entry-1",
                context={"surface": "search_memory", "retrieval_id": "retrieval-1"},
            ),
            RetrievalSignal(
                project_name="demo",
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id="entry-2",
                context={"surface": "search_memory", "retrieval_id": "retrieval-1"},
            ),
            RetrievalSignal(
                project_name="demo",
                signal_type="context_outcome",
                target_kind="context_source",
                target_id="entry-1",
                context={"outcome": "used", "retrieval_id": "retrieval-1"},
            ),
            RetrievalSignal(
                project_name="demo",
                signal_type="wake_surfaced",
                target_kind="memory_entry",
                target_id="legacy-entry",
                context={"surface": "wake"},
            ),
            RetrievalSignal(
                project_name="demo",
                signal_type="context_outcome",
                target_kind="context_source",
                target_id="legacy-entry",
                context={"outcome": "ignored"},
            ),
        ]
        for signal in signals:
            _run(backend.structured_store.save_retrieval_signal(signal))

        report = _run(
            runtime_health_report(
                backend,
                data_dir=backend.data_dir,
                project_name="demo",
            )
        )
        funnel = report["memory_funnel"]

        assert funnel["distill_scope"] == "jobs_created_within_window"
        assert funnel["distill_window_days"] == 7
        assert funnel["distinct_jobs"] == {
            "captured": 0,
            "offered": 0,
            "claimed": 0,
            "checkpointed": 0,
            "verified": 0,
            "finalized": 0,
            "promoted": 0,
            "searchable": 0,
            "surfaced": 0,
        }
        # Correlation is per surfaced source, not merely per retrieval call:
        # entry-2 has no outcome even though entry-1 from the same call was used.
        assert funnel["retrieval_feedback"]["surfaced"] == 3
        assert funnel["retrieval_feedback"]["used"] == 1
        assert funnel["retrieval_feedback"]["ignored"] == 0
        assert funnel["retrieval_feedback"]["missing_feedback"] == 2
        assert funnel["retrieval_feedback"]["correlated_retrievals"] == 1
        assert funnel["retrieval_feedback"]["correlated_surface_occurrences"] == 2
        assert funnel["retrieval_feedback"]["legacy_uncorrelated"] == 2
        assert funnel["interpretation"]["missing_feedback_is_not_negative"] is True
    finally:
        _run(backend.close())


def test_memory_funnel_reports_distinct_distill_stages_and_terminal_branches(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    review = {
        "final_user_request": "finish",
        "final_outcome": "done",
        "last_turn_status": "answered",
        "contradictions": [],
        "unfinished_work": [],
        "evidence_status": "answered",
        "promotion_decision": "promote",
    }
    try:
        job_ids: list[str] = []
        for session_id in ("promoted", "no-candidate"):
            snapshot = _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=session_id,
                        client="codex",
                        raw_content="User: finish\nAssistant: done",
                        content_type="transcript",
                        timestamp=datetime.now(timezone.utc),
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=session_id,
                    source_kind="jsonl",
                    source_uri=f"file:///{session_id}.jsonl",
                    source_text="User: finish\nAssistant: done\n",
                )
            )
            assert snapshot.distill_job_id is not None
            job_ids.append(snapshot.distill_job_id)

        backend.transcript_store.mark_distill_jobs_agent_offered("demo", job_ids)
        for job_id in job_ids:
            for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
                job_id,
                lease_owner="runtime-health-test",
                limit=100,
            ):
                backend.transcript_store.checkpoint_distill_chunk(
                    job_id,
                    chunk.id,
                    lease_owner="runtime-health-test",
                    result={"inspected": True},
                )

        entry = MemoryEntry(
            project_name="demo",
            category="decision",
            content="The promoted result is searchable.",
            source=f"distill-job:{job_ids[0]}",
            status="user_confirmed",
        )
        _run(backend.structured_store.save_memory_entry(entry))
        backend.transcript_store.finalize_distill_job(
            job_ids[0],
            semantic_review=review,
            output_candidate_ids=[entry.id],
        )
        backend.transcript_store.record_distill_completion_outcome(
            job_ids[0],
            disposition="promoted",
            reason_codes=["durable_memory_promoted"],
            promotion_summary={"promoted": 1},
            source_cleanup_status="retained",
        )
        backend.transcript_store.finalize_distill_job(
            job_ids[1],
            semantic_review=review,
            output_candidate_ids=[],
        )
        backend.transcript_store.record_distill_completion_outcome(
            job_ids[1],
            disposition="no_candidate",
            reason_codes=["no_durable_candidate"],
            promotion_summary={"promoted": 0},
            source_cleanup_status="retained",
        )
        _run(
            backend.structured_store.save_retrieval_signal(
                RetrievalSignal(
                    project_name="demo",
                    signal_type="search_hit",
                    target_kind="memory_entry",
                    target_id=entry.id,
                    context={"retrieval_id": "retrieval-promoted"},
                )
            )
        )

        report = _run(
            runtime_health_report(
                backend,
                data_dir=backend.data_dir,
                project_name="demo",
            )
        )
        funnel = report["memory_funnel"]

        assert funnel["distinct_jobs"] == {
            "captured": 2,
            "offered": 2,
            "claimed": 2,
            "checkpointed": 2,
            "verified": 2,
            "finalized": 2,
            "promoted": 1,
            "searchable": 1,
            "surfaced": 1,
        }
        stage_values = [
            funnel["distinct_jobs"][stage]
            for stage in (
                "captured",
                "offered",
                "claimed",
                "checkpointed",
                "verified",
                "finalized",
                "promoted",
                "searchable",
                "surfaced",
            )
        ]
        assert stage_values == sorted(stage_values, reverse=True)
        assert funnel["finalized"] == {
            "total": 2,
            "promoted": 1,
            "no_candidate": 1,
            "unsettled": 0,
            "successful_terminal": 2,
        }
        assert funnel["conversion"] == {
            "captured_to_offered": 1.0,
            "offered_to_claimed": 1.0,
            "claimed_to_checkpointed": 1.0,
            "checkpointed_to_verified": 1.0,
            "verified_to_finalized": 1.0,
            "promoted_to_searchable": 1.0,
            "searchable_to_surfaced": 1.0,
        }
        assert funnel["by_source_host"] == [
            {
                "source_host": "codex",
                "distinct_jobs": funnel["distinct_jobs"],
                "conversion": funnel["conversion"],
            }
        ]
    finally:
        _run(backend.close())
