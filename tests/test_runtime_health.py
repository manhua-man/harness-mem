from __future__ import annotations

import asyncio
from pathlib import Path

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
            _run(
                backend.structured_store.save_retrieval_signal(
                    RetrievalSignal(
                        project_name="demo",
                        signal_type="context_outcome",
                        target_kind="context_source",
                        target_id=f"entry-{outcome}",
                        context={"outcome": outcome},
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
