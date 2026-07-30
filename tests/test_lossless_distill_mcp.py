from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import governance_handlers, tool_handlers
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


@pytest.mark.parametrize("root_state", ["invalid_config", "missing_root"])
def test_completed_finalize_replay_recovers_missing_outcome_when_config_unavailable(
    tmp_path: Path,
    monkeypatch,
    root_state: str,
) -> None:
    project = tmp_path / root_state
    project.mkdir()
    backend = LocalMemoryBackend(tmp_path / f"data-{root_state}")
    asyncio.run(backend.init())
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id=f"recover-{root_state}",
                client="cursor",
                raw_content="recover completion outcome",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(project),
            client="cursor",
            session_id=f"recover-{root_state}",
            source_kind="jsonl",
            source_uri=f"file:///recover-{root_state}.jsonl",
            source_text="user request\nassistant completed answer\n",
        )
    )
    assert snapshot.distill_job_id is not None
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.recover-completed-distill"),
    )

    async def fake_dream(*_args, **_kwargs):
        return {"success": True, "status": "completed"}

    monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
    try:
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            snapshot.distill_job_id,
            lease_owner="recovery-test",
            limit=100,
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                snapshot.distill_job_id,
                chunk.id,
                lease_owner="recovery-test",
                result={"summary": "read"},
            )
        candidate = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content=(
                "Completed finalize retries recover their terminal outcome even when "
                "the original project configuration is unavailable."
            ),
            source=f"distill-job:{snapshot.distill_job_id}",
            confidence=0.99,
            distill_job_id=snapshot.distill_job_id,
        )
        backend.transcript_store.finalize_distill_job(
            snapshot.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
            output_candidate_ids=[candidate["entry_id"]],
        )
        if root_state == "invalid_config":
            (project / ".harness-mem.toml").write_text(
                "[distill\n",
                encoding="utf-8",
            )
            expected_reason = "completion_config_invalid"
        else:
            project.rmdir()
            expected_reason = "completion_project_root_unavailable"

        replay = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=snapshot.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )

        assert replay["success"] is True
        assert replay["idempotent_replay"] is True
        assert replay["completion_recovered"] is True
        assert replay["completion"]["disposition"] == "no_candidate"
        assert expected_reason in replay["completion"]["reason_codes"]
        assert replay["source_cleanup"]["configured"] is False
        stored = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
        assert stored is not None
        assert stored.completion_disposition == "no_candidate"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


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
        first_memory = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="Use the complete lossless session before promotion.",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        replayed_memory = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="  Use the complete lossless session\n before promotion.  ",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        first_rule = governance_handlers.tool_suggest_rule(
            project_name="demo",
            pattern="Read every transcript chunk",
            trigger="distilling a long session",
            distill_job_id=job_id,
        )
        replayed_rule = governance_handlers.tool_suggest_rule(
            project_name="demo",
            pattern="Read every transcript chunk",
            trigger="distilling a long session",
            distill_job_id=job_id,
        )
        first_relation = governance_handlers.tool_suggest_relation_fact(
            project_name="demo",
            source_entity="distill-job",
            target_entity="source-revision",
            relation_type="reads",
            evidence="All chunks completed",
            source=f"distill-job:{job_id}",
            distill_job_id=job_id,
        )
        replayed_relation = governance_handlers.tool_suggest_relation_fact(
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
        unrelated = governance_handlers.tool_suggest_memory_entry(
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
        assert finalized["completion"]["disposition"] == "no_candidate"
        assert finalized["promotion"] == {
            "suggested": 3,
            "promoted": 0,
            "rejected": 3,
            "pending": 0,
            "missing": 0,
            "evidence_admission": {
                "repository_verified": 0,
                "user_stated": 0,
                "unverified_blocked": 3,
                "contradicted": 0,
                "legacy_or_unknown": 0,
            },
        }
        assert finalized["queue_effect"]["removed_from_pending"] is True
        assert finalized["source_cleanup"] == {
            "configured": False,
            "status": "retained",
            "receipt_id": None,
            "reason_codes": ["retention_default"],
        }
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


def test_finalize_records_promoted_disposition_without_manual_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    result = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="promoted-session",
                client="cursor",
                raw_content="search rendering",
                content_type="transcript",
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id="promoted-session",
            source_kind="jsonl",
            source_uri="file:///promoted-session.jsonl",
            source_text="user request\nassistant completed answer\n",
        )
    )
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.promoted-distill"),
    )

    async def fake_dream(*_args, **_kwargs):
        return {"success": True, "status": "completed"}

    monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
    try:
        repository_evidence = tmp_path / "admission-policy.txt"
        repository_evidence.write_text(
            "One automatic distill completion path.",
            encoding="utf-8",
        )
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=result.distill_job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "read"},
        )
        candidate = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content=(
                "The project uses one automatic distill completion path so low-value "
                "sessions never require manual candidate promotion or repeated review."
            ),
            source=f"distill-job:{result.distill_job_id}",
            confidence=0.99,
            distill_job_id=result.distill_job_id,
            evidence_basis="repository",
            verification_outcome="verified",
            verification_refs=[
                {
                    "kind": "repository",
                    "locator": "admission-policy.txt",
                    "content_sha256": hashlib.sha256(
                        repository_evidence.read_bytes()
                    ).hexdigest(),
                }
            ],
        )
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )

        assert finalized["completion"] == {
            "disposition": "promoted",
            "reason_codes": ["durable_memory_promoted"],
        }
        assert finalized["promotion"]["promoted"] == 1
        stored = asyncio.run(
            backend.structured_store.get_memory_entry(candidate["entry_id"])
        )
        assert stored is not None
        assert stored.status == "auto_confirmed"
        replay = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )
        assert replay["idempotent_replay"] is True
        assert replay["completion"] == finalized["completion"]
        assert replay["promotion"] == finalized["promotion"]
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_finalize_delete_toggle_runs_audited_source_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".harness-mem.toml").write_text(
        "[distill]\ndelete_source_after_complete = true\n",
        encoding="utf-8",
    )
    session_id = "019f0000-0000-7000-8000-000000000120"
    native_root = tmp_path / ".codex" / "sessions"
    native_path = native_root / f"rollout-2026-07-28-{session_id}.jsonl"
    native_path.parent.mkdir(parents=True)
    source_text = "completed low-value session\n"
    native_path.write_bytes(source_text.encode("utf-8"))
    old = time.time() - 300
    os.utime(native_path, (old, old))

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    result = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id=session_id,
                client="codex",
                raw_content=source_text,
                content_type="transcript",
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id=session_id,
            source_kind="codex-current",
            source_uri=native_path.absolute().as_uri(),
            source_text=source_text,
            raw_bytes=source_text.encode("utf-8"),
            mtime_ns=native_path.stat().st_mtime_ns,
        )
    )
    result.source.metadata["native_cleanup_descriptor"] = {
        "version": 1,
        "allowed_root_uris": [native_root.absolute().as_uri()],
    }
    backend.transcript_store.save_source(result.source)
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.finalize-source-cleanup"),
    )

    async def fake_dream(*_args, **_kwargs):
        return {"success": True, "status": "completed"}

    monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=result.distill_job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "read"},
        )
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )

        assert finalized["completion"]["disposition"] == "no_candidate"
        assert finalized["source_cleanup"]["configured"] is True
        assert finalized["source_cleanup"]["status"] == "deleted"
        assert finalized["source_cleanup"]["receipt_id"]
        assert not native_path.exists()
        assert backend.transcript_store.reconstruct_raw(
            result.source.id,
            source_revision=result.source.source_revision,
        ) == b""
        assert asyncio.run(
            backend.verbatim_store.get(str(result.observation_id))
        ) is None
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())

def test_semantic_evidence_mode_keeps_raw_audit_and_reduces_agent_payload(
    tmp_path: Path,
) -> None:
    semantic_content = (
        "# Session\n\n"
        "## Turn 1 (turn-1)\n\n"
        "User: optimize distill throughput\n\n"
        "## Turn 2 (turn-2)\n\n"
        "User: optimize distill throughput\n\n"
        "## Turn 3 (turn-3)\n\n"
        "Assistant: progress update\n\n"
        "## Turn 4 (turn-4)\n\n"
        "Assistant: keep raw audit and use semantic evidence by default\n\n"
        "## Turn 5 (turn-5)\n\n"
        'Tool: wait -> {"cell_id":"1"}\n\n'
        "## Turn 6 (turn-6)\n\n"
        'Tool: pytest -> {"status":"passed"}\n'
    )
    source_text = "".join(
        f'{{"type":"noise","encrypted_content":"{"x" * 2000}","index":{index}}}\n'
        for index in range(80)
    )
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    result = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="semantic-session",
                client="codex",
                raw_content=semantic_content,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session", "codex"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id="semantic-session",
            source_kind="jsonl",
            source_uri="file:///semantic-session.jsonl",
            source_text=source_text,
            raw_bytes=source_text.encode("utf-8"),
        )
    )
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.semantic-distill"),
    )
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
        )

        assert packet["distill_job_id"] == result.distill_job_id
        assert packet["distill_status"] == "reviewing"
        assert packet["chunks"] == []
        assert packet["completed_chunk_count"] == packet["expected_chunk_count"]
        evidence = packet["semantic_evidence"]
        projected = "".join(chunk["content"] for chunk in evidence["chunks"])
        assert evidence["projection"] == "exchange-outline-v2"
        assert evidence["detail_level"] == "compact"
        assert evidence["budget_state"] == "within_budget"
        assert evidence["output_tokens"] <= evidence["budget_tokens"]
        assert evidence["parser_render_char_count"] == len(semantic_content)
        assert evidence["duplicate_message_count"] == 1
        assert evidence["collapsed_assistant_message_count"] == 1
        assert evidence["omitted_passive_tool_count"] == 1
        assert projected.count("U: optimize distill throughput") == 1
        assert "A: keep raw audit" in projected
        assert "progress update" not in projected
        assert "T: pytest" in projected
        assert "cell_id" not in projected
        assert evidence["semantic_char_count"] == len(projected)
        assert evidence["projection_reduction_ratio"] < 1.0
        assert evidence["raw_char_count"] == len(source_text)
        assert evidence["reduction_ratio"] < 0.01
        checkpoints = backend.transcript_store.list_distill_checkpoints(
            result.distill_job_id
        )
        assert checkpoints
        assert all(checkpoint.status == "completed" for checkpoint in checkpoints)
        assert all(
            checkpoint.result["structural_verified"] is True
            for checkpoint in checkpoints
        )

        full_semantic = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
            detail_level="full",
        )
        assert full_semantic["semantic_evidence"]["projection"] == "exchange-outline-v1"
        assert full_semantic["semantic_evidence"]["detail_level"] == "full"

        semantic_drilldown = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
            drilldown_exchange_indexes=[1],
        )
        assert semantic_drilldown["semantic_drilldown_exchange_count"] == 1
        assert "Assistant outcome: keep raw audit" in (
            semantic_drilldown["semantic_drilldown_exchanges"][0]["content"]
        )

        drilldown = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
            drilldown_chunk_indexes=[0],
        )
        assert drilldown["raw_drilldown_chunk_count"] == 1
        expected_first_chunk = backend.transcript_store.list_chunks(
            result.source.id,
            source_revision=result.source.source_revision,
        )[0]
        assert (
            drilldown["raw_drilldown_chunks"][0]["raw_content"]
            == expected_first_chunk.raw_content
        )
        query_drilldown = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
            drilldown_query="encrypted_content",
        )
        assert 1 <= query_drilldown["raw_drilldown_chunk_count"] <= 8
        assert query_drilldown["raw_drilldown_query"] == "encrypted_content"
        assert all(
            "encrypted_content" in chunk["raw_content"]
            for chunk in query_drilldown["raw_drilldown_chunks"]
        )

        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "evidence_status": "partial",
                "promotion_decision": "no_promotion",
            },
        )
        assert finalized["success"] is True
        assert finalized["structural_audit"]["coverage"] == "complete"
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
        candidate = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="Candidate is terminally rejected when semantic review blocks promotion.",
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
        assert stored.status == "rejected"
        completed = backend.transcript_store.get_distill_job(job_id)
        assert completed is not None
        assert completed.output_candidate_ids == [candidate["entry_id"]]
        assert completed.completion_disposition == "no_candidate"
        assert completed.completion_reason_codes == ["semantic_review_blocked"]
        assert completed.promotion_summary == {
            "suggested": 1,
            "promoted": 0,
            "rejected": 1,
            "pending": 0,
            "missing": 0,
            "evidence_admission": {
                "repository_verified": 0,
                "user_stated": 0,
                "unverified_blocked": 0,
                "contradicted": 0,
                "legacy_or_unknown": 0,
            },
        }
        assert completed.source_cleanup_status == "retained"
        assert finalized["completion"]["disposition"] == "no_candidate"
        assert finalized["queue_effect"]["removed_from_pending"] is True
        assert finalized["source_cleanup"]["status"] == "retained"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_deferred_recent_job_does_not_block_next_queued_job(tmp_path: Path) -> None:
    async def save(backend: LocalMemoryBackend, session_id: str) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id=session_id,
                client="cursor",
                raw_content=f"evidence for {session_id}",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=f"file:///{session_id}.jsonl",
            source_text=f"evidence for {session_id}",
        )
        assert result.distill_job_id is not None
        return result.distill_job_id

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    older_job_id = asyncio.run(save(backend, "older-session"))
    newer_job_id = asyncio.run(save(backend, "newer-session"))
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.defer-distill"),
    )
    try:
        first = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
        )
        assert first["distill_job_id"] == newer_job_id

        second = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            defer_job_id=newer_job_id,
            defer_reason="malformed historical source",
        )
        assert second["distill_job_id"] == older_job_id
        deferred = backend.transcript_store.get_distill_job(newer_job_id)
        assert deferred is not None
        assert deferred.status == "retryable"
        assert deferred.error == "malformed historical source"

        deferred_target = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            distill_job_id=newer_job_id,
        )
        assert deferred_target["success"] is False
        assert deferred_target["distill_job_id"] == newer_job_id
        assert deferred_target["distill_status"] == "retryable"
        assert deferred_target["retry_after"] is not None
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_prepare_session_distill_claims_explicit_active_job(tmp_path: Path) -> None:
    async def save(backend: LocalMemoryBackend, session_id: str) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id=session_id,
                client="cursor",
                raw_content=f"evidence for {session_id}",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=f"file:///{session_id}.jsonl",
            source_text=f"evidence for {session_id}",
        )
        assert result.distill_job_id is not None
        return result.distill_job_id

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    older_job_id = asyncio.run(save(backend, "explicit-older-session"))
    newer_job_id = asyncio.run(save(backend, "explicit-newer-session"))
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.explicit-distill"),
    )
    try:
        missing = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            distill_job_id="missing-job",
        )
        assert missing == {
            "success": False,
            "error": "distill_job_id does not belong to this project",
            "distill_job_id": "missing-job",
        }

        not_offered = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            distill_job_id=older_job_id,
        )
        assert not_offered == {
            "success": False,
            "error": "distill_job_id was not offered for Agent processing today",
            "distill_job_id": older_job_id,
            "distill_status": "queued",
            "agent_offer_day": None,
        }

        offered = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            max_jobs=2,
            daily_job_budget=2,
        )
        assert {job.id for job in offered} == {older_job_id, newer_job_id}

        selected = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            distill_job_id=older_job_id,
        )
        assert selected["success"] is True
        assert selected["distill_job_id"] == older_job_id
        assert selected["selection_source"] == "explicit"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())
