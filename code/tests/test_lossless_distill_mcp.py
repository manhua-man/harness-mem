from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.mcp import (
    distill_handlers,
    governance_handlers,
    read_search_handlers,
    tool_handlers,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.mcp.response_budget import serialized_result_tokens
from harness_mem.session_notes import (
    delete_session_notes,
    latest_session_note_path,
    session_note_path,
)


SEMANTIC_REVIEW = {
    "session_summary": "The session completed the requested implementation and verification.",
    "final_user_request": "finish the task",
    "final_outcome": "complete",
    "last_turn_status": "answered",
    "contradictions": [],
    "unfinished_work": [],
    "evidence_status": "answered",
    "promotion_decision": "promote",
}


@pytest.mark.parametrize(
    ("client", "execution_source", "expected"),
    [
        ("codex", "autonomous_worker", False),
        ("codex-archive", "autonomous_worker", True),
        ("codex", "interactive_agent", True),
    ],
)
def test_source_cleanup_is_active_only_for_user_processing(
    client: str,
    execution_source: str,
    expected: bool,
) -> None:
    job = SimpleNamespace(client=client, review_execution_source=execution_source)

    assert distill_handlers._source_cleanup_allowed(job) is expected


def test_active_session_cleanup_removes_only_selected_notes(tmp_path: Path) -> None:
    job = SessionDistillJob(
        id="note-job",
        idempotency_key="note-key",
        project_name="demo",
        project_root=str(tmp_path),
        client="codex",
        session_id="note-session",
        source_id="note-source",
        source_revision="sha256:" + "a" * 64,
    )
    notes_dir = tmp_path / "notes"
    immutable = session_note_path(notes_dir, job)
    latest = latest_session_note_path(notes_dir, job.session_id)
    unrelated = notes_dir / "other-session.md"
    immutable.parent.mkdir(parents=True)
    immutable.write_text("selected", encoding="utf-8")
    latest.write_text("selected", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")

    assert delete_session_notes(notes_dir, job) == {"removed": 2, "failed": 0}
    assert not immutable.exists()
    assert not latest.exists()
    assert unrelated.exists()


def test_compatibility_entries_never_populate_current_memory_answer_packet(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "answer-packet-data")
    asyncio.run(backend.init())
    verified_at = datetime.now(timezone.utc)
    entries = [
        MemoryEntry(
            id=f"memory-{index}",
            project_name="demo",
            category="decision",
            content=f"Durable fact {index}.",
            source="user",
            status="user_confirmed",
            evidence_basis="user_statement",
            verification_outcome="verified",
            verified_at=verified_at,
        )
        for index in (1, 2)
    ]
    for entry in entries:
        asyncio.run(backend.structured_store.save_memory_entry(entry))
    job = SessionDistillJob(
        id="job-multi-item",
        idempotency_key="key-multi-item",
        project_name="demo",
        project_root=str(tmp_path),
        client="codex",
        session_id="session-multi-item",
        source_id="source-multi-item",
        source_revision="sha256:" + "a" * 64,
        semantic_review={"final_user_request": "保存可复用结论。"},
    )

    try:
        packet = asyncio.run(
            distill_handlers._build_answer_packet(
                backend,
                job=job,
                candidate_ids=[entry.id for entry in entries],
                promotion_counts={"suggested": 2, "promoted": 2},
                runtime_reviewed=True,
            )
        )
    finally:
        asyncio.run(backend.close())

    assert packet["promotion_status"] == "not_promoted"
    assert packet["promoted_items"] == []
    assert packet["core_conclusion"] == "候选未通过晋升策略。"
    assert "promoted_items" not in packet["core_conclusion"]


def test_semantic_evidence_reuses_a_verified_appended_revision(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "append-projection-data")
    asyncio.run(backend.init())
    source_uri = "file:///append-projection.jsonl"
    base_native = b'{"event":"base"}\n'
    tail_native = b'{"event":"tail"}\n'
    base_parser = "User: inspect base\n\nAssistant: base verified\n\n"
    tail_parser = "User: inspect tail\n\nAssistant: tail verified\n\n"

    base = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="append-projection",
                client="codex",
                raw_content=base_parser,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id="append-projection",
            source_kind="jsonl",
            source_uri=source_uri,
            source_text=base_native.decode(),
            raw_bytes=base_native,
            sequence_count=1,
        )
    )
    assert base.source is not None
    base_evidence = distill_handlers._load_distill_semantic_evidence(
        backend,
        source_id=base.source.id,
        source_revision=base.source.source_revision,
        detail_level="compact",
        budget_tokens=3000,
    )
    assert base_evidence is not None
    assert base_evidence["projection_build_mode"] == "full"

    appended_native = base_native + tail_native
    appended = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="append-projection",
                client="codex",
                raw_content=base_parser + tail_parser,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id="append-projection",
            source_kind="jsonl",
            source_uri=source_uri,
            source_text=appended_native.decode(),
            raw_bytes=appended_native,
            sequence_count=2,
        )
    )
    assert appended.source is not None
    appended_evidence = distill_handlers._load_distill_semantic_evidence(
        backend,
        source_id=appended.source.id,
        source_revision=appended.source.source_revision,
        detail_level="compact",
        budget_tokens=3000,
    )

    assert appended_evidence is not None
    assert appended_evidence["projection_build_mode"] == "append"
    assert appended_evidence["projection_base_revision"] == base.source.source_revision
    assert appended_evidence["covered_sequence_count"] == 2
    asyncio.run(backend.close())


def _zero_candidate_challenge(
    *,
    source_revision: str,
    exchange_refs: list[dict] | None = None,
    check_overrides: dict[str, str] | None = None,
) -> dict:
    checks = {
        "user_correction": "absent",
        "explicit_decision": "absent",
        "successful_solution": "absent",
        "repeated_failure": "absent",
        "rule_or_preference": "absent",
        "reusable_workflow_or_fact": "absent",
        "version_or_migration": "absent",
        "unfinished_handoff": "absent",
    }
    checks.update(check_overrides or {})
    return {
        "version": "v1",
        "source_revision": source_revision,
        "evidence_fidelity": "complete",
        "future_utility": "session_only",
        "checks": checks,
        "inspected_exchange_refs": exchange_refs or [],
        "conclusion": "no_durable_candidate",
        "rationale": "The complete review found only session-local execution detail.",
    }


def test_explicit_session_rechecks_legacy_signal_false_negative(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="legacy-signal-false-negative",
                client="codex",
                raw_content="We decided to keep the governed memory workflow.",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(project),
            client="codex",
            session_id="legacy-signal-false-negative",
            source_kind="jsonl",
            source_uri="file:///legacy-signal-false-negative.jsonl",
            source_text=(
                "User: choose the durable workflow\n\n"
                "Assistant: We decided to keep the governed memory workflow.\n"
            ),
        )
    )
    assert snapshot.source is not None
    assert snapshot.distill_job_id is not None
    old_job_id = snapshot.distill_job_id
    for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
        old_job_id,
        lease_owner="legacy-agent",
        limit=100,
    ):
        backend.transcript_store.checkpoint_distill_chunk(
            old_job_id,
            chunk.id,
            lease_owner="legacy-agent",
            result={"summary": "read"},
        )
    legacy_review = {
        **SEMANTIC_REVIEW,
        "promotion_decision": "no_promotion",
        "zero_candidate_challenge": _zero_candidate_challenge(
            source_revision=snapshot.source.source_revision,
            check_overrides={"explicit_decision": "not_durable"},
        ),
    }
    backend.transcript_store.finalize_distill_job(
        old_job_id,
        semantic_review=legacy_review,
        output_candidate_ids=[],
    )
    backend.transcript_store.record_distill_completion_outcome(
        old_job_id,
        disposition="no_candidate",
        reason_codes=["zero_candidate_challenge_passed"],
        promotion_summary={},
        source_cleanup_status="retained",
    )

    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.legacy-signal-recheck"),
    )
    try:
        explicit_completed = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(project),
            client="codex",
            run_ingest=False,
            session_id="legacy-signal-false-negative",
            distill_job_id=old_job_id,
            evidence_mode="semantic",
        )
        assert explicit_completed["success"] is True
        assert explicit_completed["distill_job_id"] == old_job_id
        assert explicit_completed["agent_execution"]["path"] == "already_completed"

        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(project),
            client="codex",
            run_ingest=False,
            session_id="legacy-signal-false-negative",
            evidence_mode="semantic",
        )

        assert packet["success"] is True
        assert packet["distill_job_id"] != old_job_id
        assert packet["agent_execution"]["path"] != "already_completed"
        old_job = backend.transcript_store.get_distill_job(old_job_id)
        assert old_job is not None
        assert old_job.status == "completed"
        assert old_job.completion_disposition == "no_candidate"
        recheck_job = backend.transcript_store.get_distill_job(
            packet["distill_job_id"]
        )
        assert recheck_job is not None
        assert recheck_job.pipeline_version == (
            distill_handlers._SIGNAL_GATE_RECHECK_PIPELINE_VERSION
        )
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_explicit_session_rechecks_completed_promotion_without_current_result(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="legacy-false-promotion",
                client="codex",
                raw_content="A durable fact was claimed but never committed.",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(project),
            client="codex",
            session_id="legacy-false-promotion",
            source_kind="jsonl",
            source_uri="file:///legacy-false-promotion.jsonl",
            source_text=(
                "User: remember the durable fact\n\n"
                "Assistant: The durable fact was recorded.\n"
            ),
        )
    )
    assert snapshot.source is not None
    assert snapshot.distill_job_id is not None
    old_job_id = snapshot.distill_job_id
    for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
        old_job_id,
        lease_owner="legacy-agent",
        limit=100,
    ):
        backend.transcript_store.checkpoint_distill_chunk(
            old_job_id,
            chunk.id,
            lease_owner="legacy-agent",
            result={"summary": "read"},
        )
    backend.transcript_store.finalize_distill_job(
        old_job_id,
        semantic_review=SEMANTIC_REVIEW,
        output_candidate_ids=["legacy-candidate"],
    )
    backend.transcript_store.record_distill_completion_outcome(
        old_job_id,
        disposition="promoted",
        reason_codes=["durable_memory_promoted"],
        promotion_summary={
            "suggested": 1,
            "promoted": 1,
            "pending": 0,
            "missing": 0,
        },
        source_cleanup_status="retained",
    )

    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.current-knowledge-recheck"),
    )
    try:
        explicit_completed = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(project),
            client="codex",
            run_ingest=False,
            session_id="legacy-false-promotion",
            distill_job_id=old_job_id,
            evidence_mode="semantic",
        )
        assert explicit_completed["success"] is False
        assert explicit_completed["reason_codes"] == [
            "assimilation_candidate_results_incomplete"
        ]

        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(project),
            client="codex",
            run_ingest=False,
            session_id="legacy-false-promotion",
            evidence_mode="semantic",
        )

        assert packet["success"] is True
        assert packet["distill_job_id"] != old_job_id
        assert packet["agent_execution"]["path"] != "already_completed"
        recheck_job = backend.transcript_store.get_distill_job(
            packet["distill_job_id"]
        )
        assert recheck_job is not None
        assert recheck_job.pipeline_version == (
            distill_handlers._CURRENT_KNOWLEDGE_RECHECK_PIPELINE_VERSION
        )
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_completed_legacy_no_candidate_without_summary_requires_recheck() -> None:
    job = SimpleNamespace(
        status="completed",
        pipeline_version="lossless-distill-v1",
        completion_disposition="no_candidate",
        completion_reason_codes=["zero_candidate_challenge_passed"],
        semantic_review={
            "zero_candidate_challenge": _zero_candidate_challenge(
                source_revision="sha256:legacy"
            )
        },
    )

    assert distill_handlers._completed_job_requires_signal_gate_recheck(job) is True


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"pipeline_version": "lossless-distill-v1-signal-gate-v2"},
            False,
            id="current-policy-version",
        ),
        pytest.param({"status": "reviewing"}, False, id="not-completed"),
        pytest.param(
            {"completion_disposition": "promoted"},
            False,
            id="promoted-completion",
        ),
        pytest.param(
            {"completion_reason_codes": []},
            False,
            id="missing-challenge-reason",
        ),
    ],
)
def test_signal_gate_recheck_does_not_reopen_ineligible_jobs(
    overrides: dict,
    expected: bool,
) -> None:
    values = {
        "status": "completed",
        "pipeline_version": "lossless-distill-v1",
        "completion_disposition": "no_candidate",
        "completion_reason_codes": ["zero_candidate_challenge_passed"],
        "semantic_review": {
            "session_summary": "A complete legacy summary exists.",
            "zero_candidate_challenge": _zero_candidate_challenge(
                source_revision="sha256:legacy",
                check_overrides={"explicit_decision": "not_durable"},
            ),
        },
    }
    values.update(overrides)

    assert (
        distill_handlers._completed_job_requires_signal_gate_recheck(
            SimpleNamespace(**values)
        )
        is expected
    )


def test_zero_signal_bundle_stays_no_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        distill_handlers,
        "_load_distill_exchange_windows",
        lambda *_args, **_kwargs: [],
    )
    payload: dict = {}

    distill_handlers._attach_semantic_decision_bundle(
        SimpleNamespace(),
        payload=payload,
        source_id="source-1",
        source_revision="sha256:no-signals",
        semantic_evidence={
            "zero_candidate_required_exchange_indexes": [],
            "zero_candidate_required_exchange_reasons": {},
        },
    )

    challenge = payload["zero_candidate_challenge_template"]
    assert challenge["future_utility"] == "session_only"
    assert challenge["conclusion"] == "no_durable_candidate"
    assert set(challenge["checks"].values()) == {"absent"}


@pytest.mark.parametrize("root_state", ["invalid_config", "missing_root"])
def test_completed_finalize_replay_recovers_missing_outcome_when_config_unavailable(
    tmp_path: Path,
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
        else:
            project.rmdir()

        replay = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=snapshot.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )

        assert replay["success"] is True
        assert replay["idempotent_replay"] is True
        assert replay["completion_recovered"] is True
        assert replay["completion"]["disposition"] == "no_candidate"
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


def test_completed_legacy_promotion_receipt_is_not_replayed_as_success(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "legacy-promotion-data")
    asyncio.run(backend.init())
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="legacy-false-promotion",
                client="codex",
                raw_content="legacy false promotion",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id="legacy-false-promotion",
            source_kind="jsonl",
            source_uri="file:///legacy-false-promotion.jsonl",
            source_text="user request\nassistant answer\n",
        )
    )
    assert snapshot.distill_job_id is not None
    for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
        snapshot.distill_job_id,
        lease_owner="legacy-promotion-test",
        limit=100,
    ):
        backend.transcript_store.checkpoint_distill_chunk(
            snapshot.distill_job_id,
            chunk.id,
            lease_owner="legacy-promotion-test",
            result={"summary": "read"},
        )
    backend.transcript_store.finalize_distill_job(
        snapshot.distill_job_id,
        semantic_review=SEMANTIC_REVIEW,
        output_candidate_ids=[],
    )
    backend.transcript_store.record_distill_completion_outcome(
        snapshot.distill_job_id,
        disposition="promoted",
        reason_codes=["durable_memory_promoted"],
        promotion_summary={
            "suggested": 1,
            "promoted": 1,
            "answer_packet": {
                "promoted_items": [
                    {
                        "title": "Claimed but unwritten",
                        "fact": "This fact was never written to current knowledge.",
                    }
                ]
            },
        },
        source_cleanup_status="retained",
    )
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.legacy-false-promotion"),
    )
    try:
        replay = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=snapshot.distill_job_id,
            semantic_review=SEMANTIC_REVIEW,
        )

        assert replay["success"] is False
        assert replay["distill_status"] == "completed"
        assert replay["reason_codes"] == ["assimilation_candidate_count_mismatch"]
        assert asyncio.run(
            backend.structured_store.knowledge_store.list_entries("demo")
        ) == []
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_mcp_reads_every_lossless_chunk_before_final_review(
    tmp_path: Path,
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
            # Keep this locator intentionally relative on every supported OS.
            # ``file:///session-1.jsonl`` is rooted on POSIX but drive-relative
            # on Windows, which made the expected retention reason platform-
            # dependent in the Linux release gate.
            source_uri="file:session-1.jsonl",
            source_text=source_text,
            raw_bytes=source_text.encode("utf-8"),
        )

    source_text = "start\n" + ("complete-middle-evidence\n" * 2500) + "final-answer\n"
    (tmp_path / ".harness-mem.toml").write_text(
        "[distill]\nauto = true\n",
        encoding="utf-8",
    )
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
                evidence_mode="raw",
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
        first_memory = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "memory",
                "project_name": "demo",
                "category": "decision",
                "content": "Use the complete lossless session before promotion.",
                "source": f"distill-job:{job_id}",
                "distill_job_id": job_id,
            },
        )
        replayed_memory = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "memory",
                "project_name": "demo",
                "category": "decision",
                "content": "  Use the complete lossless session\n before promotion.  ",
                "source": f"distill-job:{job_id}",
                "distill_job_id": job_id,
            },
        )
        first_rule = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "rule",
                "project_name": "demo",
                "pattern": "Read every transcript chunk",
                "trigger": "distilling a long session",
                "distill_job_id": job_id,
            },
        )
        replayed_rule = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "rule",
                "project_name": "demo",
                "pattern": "Read every transcript chunk",
                "trigger": "distilling a long session",
                "distill_job_id": job_id,
            },
        )
        first_relation = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "relation",
                "project_name": "demo",
                "source_entity": "distill-job",
                "target_entity": "source-revision",
                "relation_type": "reads",
                "evidence": "All chunks completed",
                "source": f"distill-job:{job_id}",
                "distill_job_id": job_id,
            },
        )
        replayed_relation = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                "kind": "relation",
                "project_name": "demo",
                "source_entity": "distill-job",
                "target_entity": "source-revision",
                "relation_type": "reads",
                "evidence": "All chunks completed",
                "source": f"distill-job:{job_id}",
                "distill_job_id": job_id,
            },
        )
        assert first_relation["success"] is True, first_relation
        assert replayed_relation["success"] is True, replayed_relation
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
        assert "dream" not in finalized
        assert finalized["completion"]["disposition"] == "no_candidate"
        expected_promotion = {
            "suggested": 3,
            "promoted": 0,
            "confirmed": 0,
            "no_write": 0,
            "handoff": 0,
            "deferred": 3,
            "conflict": 0,
            "rejected": 0,
            "pending": 0,
            "missing": 0,
            "evidence_admission": {
                "repository_verified": 0,
                "user_stated": 0,
                "unverified_blocked": 3,
                "contradicted": 0,
                "legacy_or_unknown": 0,
            },
            "answer_gate": {
                "ANSWERED": 0,
                "PARTIAL": 0,
                "UNANSWERED": 3,
                "CONTRADICTED": 0,
                "STALE": 0,
                "NOT_APPLICABLE": 0,
            },
        }
        assert {
            key: value
            for key, value in finalized["promotion"].items()
            if key not in {"answer_packet", "points"}
        } == expected_promotion
        assert finalized["answer_packet"] == finalized["promotion"]["answer_packet"]
        assert finalized["answer_packet"]["answer_status"] == "UNANSWERED"
        assert finalized["answer_packet"]["promotion_status"] == "not_promoted"
        assert finalized["answer_packet"]["promoted_items"] == []
        assert finalized["queue_effect"]["removed_from_pending"] is True
        assert finalized["source_cleanup"]["configured"] is True
        assert finalized["source_cleanup"]["status"] == "retained"
        assert finalized["source_cleanup"]["receipt_id"] is None
        assert finalized["source_cleanup"]["reason_codes"] == [
            "native_source_uri_not_absolute"
        ]
        unrelated_entry = asyncio.run(
            backend.structured_store.knowledge_store.get_candidate(
                unrelated["entry_id"]
            )
        )
        assert unrelated_entry is not None
        assert unrelated_entry.status == "pending"
        assert (
            asyncio.run(
                backend.structured_store.get_memory_entry(unrelated["entry_id"])
            )
            is None
        )
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


@pytest.mark.parametrize(
    "semantic_review",
    [
        pytest.param(SEMANTIC_REVIEW, id="complete-session"),
        pytest.param(
            {
                **SEMANTIC_REVIEW,
                "session_summary": (
                    "The implementation completed while one documentation handoff "
                    "remained."
                ),
                "final_outcome": "implementation complete; documentation remains",
                "last_turn_status": "unfinished",
                "unfinished_work": ["Align the governance wording in documentation."],
                "evidence_status": "partial",
                "promotion_decision": "partial",
            },
            id="answered-candidate-with-unfinished-handoff",
        ),
        pytest.param(
            {
                **SEMANTIC_REVIEW,
                "session_summary": (
                    "The verified preference was answered while an older plan was "
                    "replaced."
                ),
                "final_outcome": "verified preference retained; old plan replaced",
                "last_turn_status": "unfinished",
                "contradictions": ["An older plan was replaced by a later decision."],
                "unfinished_work": ["Finish unrelated follow-up work."],
                "evidence_status": "partial",
                "promotion_decision": "partial",
            },
            id="answered-candidate-with-historical-contradiction",
        ),
    ],
)
def test_finalize_promotes_answered_candidate_independently_of_session_handoff(
    tmp_path: Path,
    semantic_review: dict,
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

    try:
        repository_evidence = tmp_path / "admission-policy.txt"
        repository_evidence.write_text(
            "Only hm is generated as the daily command.",
            encoding="utf-8",
        )
        seed_candidate = KnowledgeCandidate(
            id="seed-old-entry-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="Legacy hm commands are still generated.",
        )
        old_entry = KnowledgeEntry(
            id="old-hm-entry",
            project_name="demo",
            module_path=["commands"],
            title="Legacy hm commands",
            statement="Legacy hm commands are still generated.",
            verified_at=datetime.now(timezone.utc),
        )
        asyncio.run(
            backend.structured_store.knowledge_store.apply_current_change(
                candidate_before=seed_candidate,
                candidate_after=seed_candidate.model_copy(
                    update={"status": "assimilated"}
                ),
                decision=AssimilationDecision(
                    id="seed-old-entry-decision",
                    project_name="demo",
                    candidate_id=seed_candidate.id,
                    disposition="add",
                    canonical_truth_ids=[old_entry.id],
                    reason="Seed a current statement for replacement coverage.",
                ),
                added_entries=[old_entry],
                predecessor_entries=[],
                source_refs_by_entry={
                    old_entry.id: [
                        ProjectKnowledgeSourceRef(
                            label="admission-policy.txt",
                            target=repository_evidence.resolve().as_uri(),
                            kind="repository",
                            digest=hashlib.sha256(
                                repository_evidence.read_bytes()
                            ).hexdigest(),
                        )
                    ]
                },
            )
        )
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            evidence_mode="raw",
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=result.distill_job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "read"},
        )
        candidate_arguments = {
            "kind": "memory",
            "project_name": "demo",
            "category": "decision",
            "content": (
                "Only hm is generated as the daily command; legacy hm commands are "
                "not generated."
            ),
            "source": f"distill-job:{result.distill_job_id}",
            "confidence": 0.99,
            "distill_job_id": result.distill_job_id,
            "evidence_basis": "repository",
            "verification_outcome": "verified",
            "verification_refs": [
                {
                    "kind": "repository",
                    "locator": "admission-policy.txt",
                    "content_sha256": hashlib.sha256(
                        repository_evidence.read_bytes()
                    ).hexdigest(),
                }
            ],
        }
        incomplete = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments=candidate_arguments,
        )
        legacy = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **semantic_review,
                "assimilation": {
                    "version": "v1",
                    "candidate_ids": [incomplete["entry_id"]],
                    "points": [],
                },
            },
        )
        assert legacy["success"] is False
        assert legacy["reason_codes"] == ["legacy_assimilation_retired"]
        blocked = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=semantic_review,
        )
        assert blocked["success"] is False
        assert blocked["reason_codes"] == ["interactive_assimilation_incomplete"]
        assert "completion" not in blocked
        assert [
            entry.id
            for entry in asyncio.run(
                backend.structured_store.knowledge_store.list_entries("demo")
            )
        ] == [old_entry.id]

        candidate = governance_handlers.tool_govern_memory(
            action="suggest",
            arguments={
                **candidate_arguments,
                "assimilation_disposition": "replace",
                "assimilation_reason": "The new verified command behavior replaces the old one.",
                "assimilation_target_ids": [old_entry.id],
                "canonical_title": "Only hm is generated",
                "topic_path": ["commands"],
            },
        )
        assert candidate["entry_id"] == incomplete["entry_id"]
        assert candidate["idempotent_replay"] is True
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=semantic_review,
        )

        assert "completion" in finalized, finalized
        assert finalized["completion"] == {
            "disposition": "promoted",
            "reason_codes": ["durable_memory_promoted"],
        }
        assert finalized["promotion"]["promoted"] == 1
        assert finalized["promotion"]["answer_gate"] == {
            "ANSWERED": 1,
            "PARTIAL": 0,
            "UNANSWERED": 0,
            "CONTRADICTED": 0,
            "STALE": 0,
            "NOT_APPLICABLE": 0,
        }
        answer_packet = finalized["answer_packet"]
        assert answer_packet["answer_status"] == "ANSWERED"
        assert answer_packet["promotion_status"] == "promoted"
        assert answer_packet["destination_project"] == "demo"
        assert answer_packet["evidence_basis"] == ["repository"]
        assert answer_packet["verified_at"]
        assert answer_packet["knowledge_kind"] == ["knowledge"]
        assert answer_packet["knowledge_category"] == ["commands"]
        assert answer_packet["promoted_items"] == [
            {
                "title": "Only hm is generated",
                "fact": (
                    "Only hm is generated as the daily command; legacy hm commands are "
                    "not generated."
                ),
                "kind": "knowledge",
                "category": "commands",
            }
        ]
        assert "promoted_items" not in answer_packet["core_conclusion"]
        note_text = Path(finalized["note"]["path"]).read_text(encoding="utf-8")
        assert "## Answer Packet" in note_text
        assert "- 验证状态：已验证" in note_text
        assert "- 写入状态：已写入长期记忆" in note_text
        assert "知识类型：" not in note_text
        assert "知识分类：" not in note_text
        assert "（semantic / decision）" not in note_text
        assert answer_packet["promoted_items"][0]["fact"] in note_text
        assert candidate["entry_id"] not in note_text
        stored = asyncio.run(
            backend.structured_store.knowledge_store.list_entries("demo")
        )
        assert len(stored) == 1
        assert stored[0].title == "Only hm is generated"
        compatibility = asyncio.run(
            backend.structured_store.get_memory_entry(candidate["entry_id"])
        )
        assert compatibility is None
        assert (
            asyncio.run(
                backend.structured_store.knowledge_store.get_candidate(
                    candidate["entry_id"]
                )
            )
            is None
        )
        searched = read_search_handlers.tool_search_memory(
            query="daily command",
            project_name="demo",
        )
        assert searched["memories"] == [
            {
                "title": "Only hm is generated",
                "statement": (
                    "Only hm is generated as the daily command; legacy hm commands are "
                    "not generated."
                ),
            }
        ]
        old_search = read_search_handlers.tool_search_memory(
            query="Legacy hm commands are still generated",
            project_name="demo",
        )
        assert all(
            memory["statement"] != old_entry.statement
            for memory in old_search["memories"]
        )
        assert "dream" not in finalized
        replay = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review=semantic_review,
        )
        assert replay["idempotent_replay"] is True
        assert replay["completion"] == finalized["completion"]
        assert replay["promotion"] == finalized["promotion"]
        assert replay["answer_packet"] == answer_packet
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_job_bound_handoff_satisfies_durable_signal_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_SESSION_NOTES_DIR", str(tmp_path / "notes"))
    backend = LocalMemoryBackend(tmp_path / "handoff-data")
    asyncio.run(backend.init())
    result = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="handoff-session",
                client="cursor",
                raw_content="search rendering",
                content_type="transcript",
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            session_id="handoff-session",
            source_kind="jsonl",
            source_uri="file:///handoff-session.jsonl",
            source_text="user requested follow-up\nassistant left work unfinished\n",
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
        logger_instance=logging.getLogger("test.job-bound-handoff"),
    )
    try:
        tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            evidence_mode="semantic",
        )
        handoff = governance_handlers.tool_create_task_handoff(
            project_name="demo",
            task_id="finish-follow-up",
            summary="Finish the scoped follow-up from this session.",
            status="in_progress",
            next_steps=["Complete the follow-up."],
            distill_job_id=result.distill_job_id,
        )
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "last_turn_status": "unfinished",
                "evidence_status": "partial",
                "promotion_decision": "partial",
                "unfinished_work": ["Complete the follow-up."],
                "zero_candidate_challenge": {
                    "version": "v1",
                    "source_revision": result.source.source_revision,
                    "evidence_fidelity": "complete",
                    "future_utility": "durable",
                    "checks": {
                        "user_correction": "absent",
                        "explicit_decision": "absent",
                        "successful_solution": "absent",
                        "repeated_failure": "absent",
                        "rule_or_preference": "absent",
                        "reusable_workflow_or_fact": "absent",
                        "version_or_migration": "absent",
                        "unfinished_handoff": "candidate_required",
                    },
                    "inspected_exchange_refs": [],
                    "conclusion": "candidate_required",
                    "rationale": "unfinished_handoff is preserved by the job-bound handoff.",
                },
            },
        )

        assert finalized["success"] is True
        assert finalized["handoff_ids"] == [handoff["handoff_id"]]
        stored_handoff = asyncio.run(
            backend.structured_store.get_task_handoff(handoff["handoff_id"])
        )
        assert stored_handoff is not None
        assert stored_handoff.context["distill_job_id"] == result.distill_job_id
        assert Path(finalized["note"]["path"]).is_file()
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
        "[distill]\nauto = true\n",
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

    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="raw",
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
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": _zero_candidate_challenge(
                    source_revision=result.source.source_revision
                ),
            },
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
        "Assistant: We decided to keep raw audit and default to semantic evidence\n\n"
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
        )

        assert packet["distill_job_id"] == result.distill_job_id
        assert packet["evidence_mode"] == "semantic"
        assert packet["distill_status"] == "reviewing"
        assert packet["zero_candidate_challenge_version"] == "v1"
        assert packet["chunks"] == []
        assert packet["completed_chunk_count"] == packet["expected_chunk_count"]
        evidence = packet["semantic_evidence"]
        projected = "".join(chunk["content"] for chunk in evidence["chunks"])
        assert evidence["projection"] == "exchange-outline-v2"
        assert evidence["detail_level"] == "compact"
        assert evidence["budget_state"] == "within_budget"
        assert evidence["output_tokens"] <= evidence["budget_tokens"]
        serialized_tokens, tokenizer, serialized_chars = serialized_result_tokens(
            packet
        )
        assert packet["response_budget"] == {
            "contract_version": "serialized-response-budget-v1",
            "scope": "mcp_content_text",
            "requested_target_tokens": 3000,
            "evidence_tokens": evidence["output_tokens"],
            "protocol_tokens": serialized_tokens - evidence["output_tokens"],
            "protocol_tokens_basis": "serialized_minus_evidence_estimate",
            "serialized_tokens": serialized_tokens,
            "serialized_chars": serialized_chars,
            "tokenizer": tokenizer,
            "outcome": "within_target",
            "reason": None,
            "hard_truncation_applied": False,
        }
        assert evidence["parser_render_char_count"] == len(semantic_content)
        assert evidence["duplicate_message_count"] == 1
        assert evidence["collapsed_assistant_message_count"] == 1
        assert evidence["omitted_passive_tool_count"] == 1
        assert projected.count("U: optimize distill throughput") == 1
        assert "keep raw audit" in projected
        assert "progress update" not in projected
        assert "T: pytest" in projected
        assert "cell_id" not in projected
        assert evidence["semantic_char_count"] == len(projected)
        assert evidence["projection_reduction_ratio"] <= 1.5
        assert evidence["raw_char_count"] == len(source_text)
        assert evidence["reduction_ratio"] < 0.01
        decision_indexes = [
            item["exchange_index"]
            for item in packet["semantic_decision_exchanges"]
        ]
        assert decision_indexes == evidence[
            "zero_candidate_required_exchange_indexes"
        ]
        assert packet["semantic_decision_exchange_count"] == len(decision_indexes)
        assert packet["zero_candidate_exchange_refs"] == [
            {
                "exchange_index": item["exchange_index"],
                "content_sha256": item["content_sha256"],
            }
            for item in packet["semantic_decision_exchanges"]
        ]
        challenge_template = packet["zero_candidate_challenge_template"]
        assert challenge_template["source_revision"] == result.source.source_revision
        assert challenge_template["inspected_exchange_refs"] == packet[
            "zero_candidate_exchange_refs"
        ]
        signaled_checks = {
            reason
            for reasons in evidence[
                "zero_candidate_required_exchange_reasons"
            ].values()
            for reason in reasons
        }
        detected_checks = signaled_checks & set(challenge_template["checks"])
        assert detected_checks
        assert challenge_template["future_utility"] == "durable"
        assert challenge_template["conclusion"] == "candidate_required"
        for check_name, finding in challenge_template["checks"].items():
            assert finding == (
                "candidate_required" if check_name in detected_checks else "absent"
            )
        assert packet["agent_execution"] == {
            "contract_version": "agent-distill-fast-path-v1",
            "path": "prepare_then_finalize",
            "target_mcp_calls": 2,
            "completed_mcp_calls": 1,
            "next_tool": "finalize_session_distill",
            "additional_prepare_required": False,
            "additional_prepare_allowed_when": [
                "candidate_needs_raw_proof",
                "legacy_raw_fallback",
            ],
        }
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
        assert "Assistant outcome: We decided to keep raw audit" in (
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
        assert query_drilldown["raw_drilldown_chunk_count"] >= 1
        assert query_drilldown["raw_drilldown_query"] == "encrypted_content"
        assert all(
            "encrypted_content" in chunk["raw_content"]
            for chunk in query_drilldown["raw_drilldown_chunks"]
        )

        missing_challenge = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
            },
        )
        assert missing_challenge["success"] is False
        assert missing_challenge["error"] == "zero_candidate_challenge_required"
        assert (
            backend.transcript_store.get_distill_job(result.distill_job_id).status
            == "reviewing"
        )

        wrong_hash = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": _zero_candidate_challenge(
                    source_revision=result.source.source_revision,
                    exchange_refs=[
                        {
                            "exchange_index": item["exchange_index"],
                            "content_sha256": "0" * 64,
                        }
                        for item in semantic_drilldown[
                            "semantic_drilldown_exchanges"
                        ]
                    ],
                ),
            },
        )
        assert wrong_hash["success"] is False
        assert wrong_hash["error"] == "zero_candidate_exchange_proof_incomplete"

        blocked_template = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": challenge_template,
            },
        )
        assert blocked_template["success"] is False
        assert blocked_template["error"] == "zero_candidate_challenge_requires_candidate"

        downgraded_checks = {
            name: "not_durable" if value == "candidate_required" else value
            for name, value in challenge_template["checks"].items()
        }
        generic_downgrade = {
            **challenge_template,
            "future_utility": "session_only",
            "checks": downgraded_checks,
            "conclusion": "no_durable_candidate",
            "rationale": "The complete review found only session-local execution detail.",
        }
        unjustified = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": generic_downgrade,
            },
        )
        assert unjustified["success"] is False
        assert unjustified["error"] == "zero_candidate_signal_downgrade_unjustified"

        labels_only = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": {
                    **generic_downgrade,
                    "rationale": ", ".join(sorted(detected_checks)),
                },
            },
        )
        assert labels_only["success"] is False
        assert labels_only["error"] == "zero_candidate_signal_downgrade_unjustified"

        reviewed_downgrade = {
            **generic_downgrade,
            "rationale": (
                "Reviewed as session-only after inspecting: "
                + ", ".join(sorted(detected_checks))
                + "."
            ),
        }
        finalized = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=result.distill_job_id,
            semantic_review={
                **SEMANTIC_REVIEW,
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": reviewed_downgrade,
            },
        )
        assert finalized["success"] is True
        assert finalized["structural_audit"]["coverage"] == "complete"
        assert finalized["answer_packet"] == {
            "answer_status": "NOT_APPLICABLE",
            "question": "finish the task",
            "core_conclusion": "本次会话没有需要写入的长期记忆。",
            "evidence_basis": [],
            "evaluated_at": finalized["answer_packet"]["evaluated_at"],
            "verified_at": None,
            "promotion_status": "not_promoted",
            "promoted_items": [],
                "destination_project": "demo",
                "knowledge_kind": [],
                "knowledge_category": [],
                "point_results": [],
            }
        assert finalized["session_summary"] == {
            "session_id": "semantic-session",
            "summary": SEMANTIC_REVIEW["session_summary"],
            "final_outcome": "complete",
            "last_turn_status": "answered",
            "unfinished_work": [],
            "memory_disposition": "no_candidate",
        }
        completed_replay = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="semantic",
            session_id="semantic-session",
        )
        assert completed_replay["success"] is True, completed_replay
        assert completed_replay["distill_status"] == "completed"
        assert completed_replay["selection_source"] == "explicit_session"
        assert completed_replay["session_summary"] == finalized["session_summary"]
        assert completed_replay["agent_execution"] == {
            "contract_version": "agent-distill-fast-path-v1",
            "path": "already_completed",
            "target_mcp_calls": 1,
            "completed_mcp_calls": 1,
            "next_tool": None,
            "additional_prepare_required": False,
        }
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_finalize_does_not_auto_review_before_all_chunks_complete(
    tmp_path: Path,
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


@pytest.mark.parametrize(
    ("finalize_fails_once", "unverified_promotion"),
    [(False, False), (True, False), (False, True)],
)
def test_completed_job_retries_current_knowledge_write_without_duplicate_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finalize_fails_once: bool,
    unverified_promotion: bool,
) -> None:
    (tmp_path / ".harness-mem.toml").write_text(
        "[distill]\nauto = true\n",
        encoding="utf-8",
    )

    async def setup(backend: LocalMemoryBackend) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id=f"separated-order-{finalize_fails_once}",
                client="codex",
                raw_content="derived rendering",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id=f"separated-order-{finalize_fails_once}",
            source_kind="jsonl",
            source_uri=f"file:///separated-order-{finalize_fails_once}.jsonl",
            source_text="User: retain verified knowledge\nAssistant: done\n",
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
        logger_instance=logging.getLogger("test.separated-finalize-order"),
    )
    apply_calls = 0
    finalize_calls = 0
    original_finalize = backend.transcript_store.finalize_distill_job

    async def bound_candidates(*_args, **_kwargs):
        return ["candidate-1"]

    async def apply_or_fail(*_args, **_kwargs):
        nonlocal apply_calls
        apply_calls += 1
        if unverified_promotion:
            return {
                "suggested": 1,
                "promoted": 1,
                "confirmed": 0,
                "no_write": 0,
                "handoff": 0,
                "deferred": 0,
                "conflict": 0,
                "rejected": 0,
                "missing": 0,
                "pending": 0,
                "points": [
                    {
                        "candidate_id": "candidate-1",
                        "disposition": "add",
                        "canonical_truth_ids": ["missing-current-knowledge"],
                    }
                ],
            }
        if not finalize_fails_once and apply_calls == 1:
            raise RuntimeError("injected assimilation failure")
        return {
            "suggested": 1,
            "promoted": 0,
            "confirmed": 0,
            "no_write": 1,
            "handoff": 0,
            "deferred": 0,
            "conflict": 0,
            "rejected": 0,
            "missing": 0,
            "pending": 0,
            "points": [
                {
                    "candidate_id": "candidate-1",
                    "disposition": "no_write",
                    "canonical_truth_ids": [],
                }
            ],
        }

    def flaky_finalize(*args, **kwargs):
        nonlocal finalize_calls
        finalize_calls += 1
        if finalize_fails_once and finalize_calls == 1:
            raise RuntimeError("injected finalize persistence failure")
        return original_finalize(*args, **kwargs)

    monkeypatch.setattr(distill_handlers, "separated_job_candidate_ids", bound_candidates)
    monkeypatch.setattr(distill_handlers, "apply_separated_assimilation", apply_or_fail)
    monkeypatch.setattr(backend.transcript_store, "finalize_distill_job", flaky_finalize)
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="raw",
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "complete"},
        )
        review = {
            **SEMANTIC_REVIEW,
            "promotion_decision": "no_promotion",
            "assimilation": {
                "version": "separated-v1",
                "candidate_ids": ["candidate-1"],
                "points": [],
            },
        }

        unleased = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=job_id,
            semantic_review=review,
        )
        assert unleased["success"] is False
        assert unleased["error"] == "trusted_review_lease_required"
        assert apply_calls == 0
        lease_owner = "trusted-separated-worker"
        claimed = backend.transcript_store.claim_distill_review(
            job_id,
            lease_owner=lease_owner,
            execution_source="test",
        )
        assert claimed is not None

        if unverified_promotion:
            result = tool_handlers.tool_finalize_session_distill(
                project_name="demo",
                job_id=job_id,
                semantic_review=review,
                _review_lease_owner=lease_owner,
            )
            assert result["success"] is False
            assert result["reason_codes"] == ["promotion_write_unreadable"]
        elif finalize_fails_once:
            with pytest.raises(RuntimeError, match="finalize persistence failure"):
                tool_handlers.tool_finalize_session_distill(
                    project_name="demo",
                    job_id=job_id,
                    semantic_review=review,
                    _review_lease_owner=lease_owner,
                )
        else:
            result = tool_handlers.tool_finalize_session_distill(
                project_name="demo",
                job_id=job_id,
                semantic_review=review,
                _review_lease_owner=lease_owner,
            )
            assert result["success"] is False
            assert result["error"] == "current knowledge was not saved"
            assert result["reason_codes"] == ["injected assimilation failure"]
        stored = backend.transcript_store.get_distill_job(job_id)
        assert stored is not None
        assert stored.status != "completed"
        assert stored.completion_disposition is None

        if finalize_fails_once:
            result = tool_handlers.tool_finalize_session_distill(
                project_name="demo",
                job_id=job_id,
                semantic_review=review,
                _review_lease_owner=lease_owner,
            )
            assert result["success"] is True
            assert apply_calls == 2
            assert finalize_calls == 2
            assert backend.transcript_store.get_distill_job(job_id).status == "completed"
        elif unverified_promotion:
            assert apply_calls == 1
            assert finalize_calls == 0
        else:
            result = tool_handlers.tool_finalize_session_distill(
                project_name="demo",
                job_id=job_id,
                semantic_review=review,
                _review_lease_owner=lease_owner,
            )
            assert result["success"] is True
            assert apply_calls == 2
            assert finalize_calls == 1
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


@pytest.mark.parametrize(
    "preflight_fault",
    ["lease_commit_claim", "source_revision", "content_address"],
)
def test_trusted_assimilation_preflight_blocks_truth_write_on_stale_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preflight_fault: str,
) -> None:
    (tmp_path / ".harness-mem.toml").write_text(
        "[distill]\nauto = true\n",
        encoding="utf-8",
    )

    async def setup(backend: LocalMemoryBackend) -> str:
        result = await persist_session_snapshot(
            backend,
            Observation(
                session_id=f"separated-preflight-{preflight_fault}",
                client="codex",
                raw_content="derived rendering",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
                tags=["session"],
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id=f"separated-preflight-{preflight_fault}",
            source_kind="jsonl",
            source_uri=f"file:///separated-preflight-{preflight_fault}.jsonl",
            source_text="User: retain verified knowledge\nAssistant: done\n",
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
        logger_instance=logging.getLogger("test.separated-preflight"),
    )

    async def bound_candidates(*_args, **_kwargs):
        return ["candidate-1"]

    async def must_not_apply(*_args, **_kwargs):
        raise AssertionError("truth write ran before trusted preflight")

    monkeypatch.setattr(distill_handlers, "separated_job_candidate_ids", bound_candidates)
    monkeypatch.setattr(distill_handlers, "apply_separated_assimilation", must_not_apply)
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            evidence_mode="raw",
        )
        chunk = packet["chunks"][0]
        tool_handlers.tool_submit_distill_chunk(
            job_id=job_id,
            chunk_id=chunk["chunk_id"],
            lease_owner=packet["lease_owner"],
            result={"summary": "complete"},
        )
        lease_owner = "trusted-preflight-worker"
        claimed = backend.transcript_store.claim_distill_review(
            job_id,
            lease_owner=lease_owner,
            execution_source="test",
        )
        assert claimed is not None
        if preflight_fault == "lease_commit_claim":
            monkeypatch.setattr(
                backend.transcript_store,
                "renew_distill_review_lease",
                lambda *_args, **_kwargs: False,
            )
        elif preflight_fault == "source_revision":
            original_get_source = backend.transcript_store.get_source

            def stale_source(source_id):
                source = original_get_source(source_id)
                assert source is not None
                return source.model_copy(update={"source_revision": "sha256:stale"})

            monkeypatch.setattr(backend.transcript_store, "get_source", stale_source)
        else:
            monkeypatch.setattr(
                backend.transcript_store,
                "reconstruct",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    ValueError("transcript chunk content-address mismatch")
                ),
            )
        review = {
            **SEMANTIC_REVIEW,
            "promotion_decision": "no_promotion",
            "assimilation": {
                "version": "separated-v1",
                "candidate_ids": ["candidate-1"],
                "points": [],
            },
        }

        result = tool_handlers.tool_finalize_session_distill(
            project_name="demo",
            job_id=job_id,
            semantic_review=review,
            _review_lease_owner=lease_owner,
        )

        assert result["success"] is False
        assert result["error"] == "trusted_assimilation_precondition_failed"
        assert result["reason_codes"] == [
            {
                "lease_commit_claim": "review_lease_commit_claim_failed",
                "source_revision": "source_revision_changed",
                "content_address": "source_content_address_invalid",
            }[preflight_fault]
        ]
        stored = backend.transcript_store.get_distill_job(job_id)
        assert stored is not None and stored.status != "completed"
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
            evidence_mode="raw",
        )

        assert payload["distill_mode"] == "legacy_partial"
        assert payload["coverage"] == "legacy_partial"
        assert payload["distill_job_id"] is None
        assert payload["distill_status"] == "not_queued"
        assert "status" not in payload
        assert "not as complete lossless session evidence" in payload["distill_instructions"][1]
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
    review_overrides: dict,
) -> None:
    (tmp_path / ".harness-mem.toml").write_text(
        "[distill]\nauto = true\n",
        encoding="utf-8",
    )
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

    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            evidence_mode="raw",
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
            "answer_status": "ANSWERED",
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
        assert stored is None
        assert (
            asyncio.run(
                backend.structured_store.knowledge_store.get_candidate(
                    candidate["entry_id"]
                )
            )
            is None
        )
        completed = backend.transcript_store.get_distill_job(job_id)
        assert completed is not None
        assert completed.output_candidate_ids == [candidate["entry_id"]]
        assert completed.completion_disposition == "no_candidate"
        assert completed.completion_reason_codes == ["semantic_review_blocked"]
        expected_promotion = {
            "suggested": 1,
            "promoted": 0,
            "confirmed": 0,
            "no_write": 0,
            "handoff": 0,
            "deferred": 0,
            "conflict": 0,
            "rejected": 1,
            "pending": 0,
            "missing": 0,
            "evidence_admission": {
                "repository_verified": 0,
                "user_stated": 0,
                "unverified_blocked": 1,
                "contradicted": 0,
                "legacy_or_unknown": 0,
            },
            "answer_gate": {
                "ANSWERED": 0,
                "PARTIAL": 0,
                "UNANSWERED": 1,
                "CONTRADICTED": 0,
                "STALE": 0,
                "NOT_APPLICABLE": 0,
            },
        }
        assert {
            key: value
            for key, value in finalized["promotion"].items()
            if key not in {"answer_packet", "points"}
        } == expected_promotion
        assert finalized["answer_packet"] == finalized["promotion"]["answer_packet"]
        assert finalized["answer_packet"]["answer_status"] == "UNANSWERED"
        assert finalized["answer_packet"]["promotion_status"] == "not_promoted"
        assert finalized["answer_packet"]["promoted_items"] == []
        assert {
            key: value
            for key, value in completed.promotion_summary.items()
            if key not in {"answer_packet", "points"}
        } == expected_promotion
        answer_packet = completed.promotion_summary["answer_packet"]
        assert answer_packet["answer_status"] == "UNANSWERED"
        assert answer_packet["promotion_status"] == "not_promoted"
        assert answer_packet["promoted_items"] == []
        assert answer_packet["destination_project"] == "demo"
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

        selected_without_prior_offer = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            distill_job_id=older_job_id,
        )
        assert selected_without_prior_offer["success"] is True
        assert selected_without_prior_offer["distill_job_id"] == older_job_id
        assert selected_without_prior_offer["selection_source"] == "explicit"

        offered = pending_distill_jobs(
            backend,
            project_name="demo",
            max_jobs=2,
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


def test_prepare_session_distill_activates_explicit_parked_session(tmp_path: Path) -> None:
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
    parked_job_id = asyncio.run(save(backend, "explicit-parked-oldest"))
    active_job_id = asyncio.run(save(backend, "active-newer-1"))
    asyncio.run(save(backend, "active-newer-2"))
    backend.transcript_store.rebalance_distill_jobs(
        "demo",
        target_active=2,
        recent_first=True,
    )
    parked = backend.transcript_store.get_distill_job(parked_job_id)
    assert parked is not None
    assert parked.status == "parked"

    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.explicit-parked-distill"),
    )
    try:
        active_selected = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            session_id="active-newer-1",
        )
        assert active_selected["success"] is True
        assert active_selected["distill_job_id"] == active_job_id
        assert active_selected["selection_source"] == "explicit_session"
        selected = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="cursor",
            run_ingest=False,
            session_id="explicit-parked-oldest",
        )
        assert selected["success"] is True
        assert selected["distill_job_id"] == parked_job_id
        assert selected["session_id"] == "explicit-parked-oldest"
        assert selected["selection_source"] == "explicit_session_parked"
        activated = backend.transcript_store.get_distill_job(parked_job_id)
        assert activated is not None
        assert activated.status in {"processing", "reviewing"}
        assert activated.agent_offer_count == 1
        assert activated.agent_offer_day == datetime.now(timezone.utc).date().isoformat()
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())


def test_prepare_session_distill_recovers_fully_checkpointed_review_retry(
    tmp_path: Path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    result = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="review-retry-session",
                client="codex",
                raw_content="User: inspect the result\n\nAssistant: inspection finished\n",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            session_id="review-retry-session",
            source_kind="jsonl",
            source_uri="file:///review-retry-session.jsonl",
            source_text="User: inspect the result\n\nAssistant: inspection finished\n",
        )
    )
    assert result.distill_job_id is not None
    job_id = result.distill_job_id
    for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
        job_id,
        lease_owner="review-worker",
        limit=100,
    ):
        backend.transcript_store.checkpoint_distill_chunk(
            job_id,
            chunk.id,
            lease_owner="review-worker",
            result={"structural_verified": True},
        )
    deferred = backend.transcript_store.defer_distill_job(
        job_id,
        error="provider evidence binding failed",
    )
    assert deferred.retry_after is not None
    deferred.retry_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    backend.transcript_store._distill._upsert_job_locked(deferred)
    backend.transcript_store._conn.commit()

    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.review-retry-distill"),
    )
    try:
        packet = tool_handlers.tool_prepare_session_distill(
            project_name="demo",
            project_root=str(tmp_path),
            client="codex",
            run_ingest=False,
            session_id="review-retry-session",
            evidence_mode="semantic",
            detail_level="full",
        )
        assert packet["success"] is True
        assert packet["distill_job_id"] == job_id
        assert packet["distill_status"] == "reviewing"
        assert packet["completed_chunk_count"] == packet["expected_chunk_count"]
        assert packet["semantic_evidence"]["projection"] == "exchange-outline-v1"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())
