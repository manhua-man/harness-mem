from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


SEMANTIC_REVIEW = {
    "final_user_request": "finish the task",
    "final_outcome": "complete",
    "last_turn_status": "answered",
    "contradictions": [],
    "unfinished_work": [],
    "evidence_status": "answered",
    "promotion_decision": "promote",
}


def test_mcp_reads_every_lossless_chunk_before_final_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def setup(backend: LocalMemoryBackend, source_text: str) -> None:
        await persist_session_snapshot(
            backend,
            Observation(
                session_id="session-1",
                client="cursor",
                raw_content="search rendering",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session", "cursor"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id="session-1",
            source_kind="jsonl",
            source_uri="file:///session-1.jsonl",
            source_text=source_text,
            raw_bytes=source_text.encode("utf-8"),
        )

    source_text = "start\n" + ("complete-middle-evidence\n" * 2500) + "final-answer\n"
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    asyncio.run(setup(backend, source_text))
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.lossless-distill"),
    )

    async def fake_dream(*_args, **_kwargs):
        return {"success": True, "status": "completed", "job_id": "dream-1"}

    monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
    try:
        collected: list[str] = []
        job_id = ""
        while True:
            packet = tool_handlers.tool_prepare_session_distill(
                project_name="demo",
                project_root=str(tmp_path),
                client="cursor",
                run_ingest=False,
                chunk_limit=1,
            )
            job_id = packet["distill_job_id"]
            if packet["distill_status"] == "reviewing":
                assert len(packet["chunk_results"]) == packet["expected_chunk_count"]
                break
            assert packet["chunk_count"] == 1
            chunk = packet["chunks"][0]
            assert "[TRUNCATED]" not in chunk["raw_content"]
            collected.append(chunk["raw_content"])
            submitted = tool_handlers.tool_submit_distill_chunk(
                job_id=job_id,
                chunk_id=chunk["chunk_id"],
                lease_owner=packet["lease_owner"],
                result={"summary": f"read chunk {chunk['chunk_index']}"},
            )
            assert submitted["success"] is True

        assert "".join(collected) == source_text
        first_memory = tool_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="Use the complete lossless session before promotion.",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        replayed_memory = tool_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="  Use the complete lossless session\n before promotion.  ",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        first_rule = tool_handlers.tool_suggest_rule(
            project_name="demo",
            pattern="Read every transcript chunk",
            trigger="distilling a long session",
            distill_job_id=job_id,
        )
        replayed_rule = tool_handlers.tool_suggest_rule(
            project_name="demo",
            pattern="Read every transcript chunk",
            trigger="distilling a long session",
            distill_job_id=job_id,
        )
        first_relation = tool_handlers.tool_suggest_relation_fact(
            project_name="demo",
            source_entity="distill-job",
            target_entity="source-revision",
            relation_type="reads",
            evidence="All chunks completed",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        replayed_relation = tool_handlers.tool_suggest_relation_fact(
            project_name="demo",
            source_entity="distill-job",
            target_entity="source-revision",
            relation_type="reads",
            evidence="All chunks completed",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        assert replayed_memory["entry_id"] == first_memory["entry_id"]
        assert replayed_memory["idempotent_replay"] is True
        assert replayed_rule["candidate_id"] == first_rule["candidate_id"]
        assert replayed_rule["idempotent_replay"] is True
        assert replayed_relation["fact_id"] == first_relation["fact_id"]
        assert replayed_relation["idempotent_replay"] is True
        unrelated = tool_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="This pending candidate belongs to another workflow.",
            source="manual-review",
            confidence=0.99,
        )
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=job_id,
            semantic_review=SEMANTIC_REVIEW,
        )
        assert finalized["success"] is True
        assert finalized["structural_audit"]["coverage"] == "complete"
        assert finalized["dream"]["job_id"] == "dream-1"
        unrelated_entry = asyncio.run(
            backend.structured_store.get_memory_entry(unrelated["entry_id"])
        )
        assert unrelated_entry is not None
        assert unrelated_entry.status == "pending"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_finalize_does_not_auto_review_before_all_chunks_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def setup(backend: LocalMemoryBackend) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id="session-1",
                client="cursor",
                raw_content="search rendering",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session", "cursor"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id="session-1",
            source_kind="jsonl",
            source_uri="file:///session-1.jsonl",
            source_text="unprocessed transcript\n",
        )
        return result.distill_job_id

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    job_id = asyncio.run(setup(backend))
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.lossless-distill-order"),
    )

    async def fail_auto_review(*_args, **_kwargs):
        raise AssertionError("auto-review ran before structural finalization")

    monkeypatch.setattr(tool_handlers, "auto_review_candidates", fail_auto_review)
    try:
        with pytest.raises(ValueError, match="not all distill chunks are complete"):
            tool_handlers.tool_finalize_session_distill(
                project_name="demo",
                job_id=job_id,
                semantic_review=SEMANTIC_REVIEW,
            )
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_legacy_observations_do_not_create_a_lossless_distill_job(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.legacy-distill"),
    )
    try:
        observation = Observation(
            id="legacy-observation",
            session_id="old-session",
            client="cursor",
            raw_content="older derived rendering",
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": "demo", "source_coverage": "legacy_partial"},
            tags=["session"],
        )
        asyncio.run(backend.verbatim_store.save(observation))

        payload = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
        )

        assert payload["distill_mode"] == "legacy_partial"
        assert payload["coverage"] == "legacy_partial"
        assert payload["distill_job_id"] is None
        assert payload["distill_status"] == "not_queued"
        assert "not as a lossless session-distill packet" in payload["distill_instructions"][1]
        assert backend.reflection_job_store.list(project_name="demo", limit=10) == []
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


@pytest.mark.parametrize(
    "review_overrides",
    [
        {"promotion_decision": "partial", "evidence_status": "partial"},
        {"promotion_decision": "no_promotion", "evidence_status": "partial"},
        {"promotion_decision": "blocked", "evidence_status": "partial"},
        {
            "promotion_decision": "promote",
            "evidence_status": "contradicted",
            "contradictions": ["final answer conflicts with earlier evidence"],
        },
        {
            "promotion_decision": "promote",
            "last_turn_status": "unfinished",
            "unfinished_work": ["verification remains"],
        },
    ],
)
def test_semantic_review_blocks_promotion_and_dream(
    tmp_path: Path,
    monkeypatch,
    review_overrides: dict,
) -> None:
    async def setup(backend: LocalMemoryBackend) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id="blocked-session",
                client="cursor",
                raw_content="derived rendering",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id="blocked-session",
            source_kind="jsonl",
            source_uri="file:///blocked-session.jsonl",
            source_text="user request\nassistant answer\n",
        )
        return result.distill_job_id

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    job_id = asyncio.run(setup(backend))
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.blocked-distill"),
    )

    async def fail_dream(*_args, **_kwargs):
        raise AssertionError("Dream ran after semantic review blocked promotion")

    monkeypatch.setattr(tool_handlers, "dream_auto_tick", fail_dream)
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "read complete session"},
        )
        candidate = tool_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="Candidate must stay pending when review blocks promotion.",
            source=f"distill-job:{job_id}",
            confidence=0.99,
            distill_job_id=job_id,
        )
        review = {
            **SEMANTIC_REVIEW,
            **review_overrides,
        }
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=job_id,
            semantic_review=review,
        )

        assert finalized["success"] is True
        assert finalized["auto_review"]["skipped"] is True
        assert "dream" not in finalized
        stored = asyncio.run(
            backend.structured_store.get_memory_entry(candidate["entry_id"])
        )
        assert stored is not None
        assert stored.status == "pending"
        completed = backend.transcript_store.get_distill_job(job_id)
        assert completed is not None
        assert completed.output_candidate_ids == [candidate["entry_id"]]
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())
