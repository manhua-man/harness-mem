"""Per-signal-type unit tests for the v2.3.0 retrieval-signal write paths.

One test per signal type, each one exercising the real call site (wake
renderer, ``read_api.search_memory``, ``auto_review_candidates``,
``tool_record_skill_result``, ``tool_confirm_supersede``) plus a
resilience test that proves the primary mutation still succeeds even
when the signal-table write blows up.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.commands.wake import cmd_wake_up
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RuleCandidate,
    Skill,
    SupersedeCandidate,
)
from harness_mem.mcp import server as mcp_server
from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run


# --- helpers ---------------------------------------------------------------


def _seed_confirmed_rule(
    backend: LocalMemoryBackend, project_name: str, *, rule_id: str | None = None
) -> str:
    rule = ConfirmedRule(
        id=rule_id or str(uuid4()),
        project_name=project_name,
        trigger="Before changing IPC code",
        pattern=(
            "On Windows prefer Tauri invoke over emit for any IPC "
            "payload larger than ~1MB."
        ),
        source_candidate_id="seed-candidate-id",
    )
    return run(backend.structured_store.save_confirmed_rule(rule))


def _seed_confirmed_memory_entry(
    backend: LocalMemoryBackend, project_name: str, *, content: str | None = None
) -> str:
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content
        or "SQLite FTS5 is used for full-text search indexing in this project.",
        confidence=0.9,
        source="obs-seed",
        status="accepted",
        tags=["architecture"],
    )
    return run(backend.structured_store.save_memory_entry(entry))


def _seed_skill(backend: LocalMemoryBackend, project_name: str) -> Skill:
    skill = Skill(
        project_name=project_name,
        name="Focused validation loop",
        activation_condition="Need to validate runtime behavior",
        steps=["Run focused tests", "Run full pytest"],
        termination_condition="Validation passes",
    )
    run(backend.structured_store.save_skill(skill))
    return skill


# --- 1. wake_surfaced (memory_entry) --------------------------------------


def test_wake_surfaced_signal_emitted_for_memory_entry(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_name = "sig-wake-entry"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry_id = _seed_confirmed_memory_entry(backend, project_name)
    finally:
        run(backend.close())

    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    capsys.readouterr()  # drain wake output so it doesn't pollute test logs

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="wake_surfaced", target_kind="memory_entry"
            )
        )
    finally:
        run(backend.close())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.target_id == entry_id
    assert signal.context == {"source": "wake"}


# --- 2. wake_surfaced (rule) -----------------------------------------------


def test_wake_surfaced_signal_emitted_for_rule(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_name = "sig-wake-rule"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        rule_id = _seed_confirmed_rule(backend, project_name)
    finally:
        run(backend.close())

    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    capsys.readouterr()

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="wake_surfaced", target_kind="rule"
            )
        )
    finally:
        run(backend.close())

    assert len(signals) == 1
    assert signals[0].target_id == rule_id
    assert signals[0].context == {"source": "wake"}


# --- 3. search_hit ---------------------------------------------------------


def test_search_hit_signal_emitted_per_returned_entry(data_dir: Path) -> None:
    project_name = "sig-search"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry_id = _seed_confirmed_memory_entry(
            backend,
            project_name,
            content=(
                "We use SQLite FTS5 with porter tokenizer for full-text "
                "search across structured memory entries."
            ),
        )

        entries, _observations = run(
            search_memory(
                backend,
                project_name=project_name,
                query="SQLite FTS5",
                memory_entry_limit=20,
            )
        )
        assert any(entry.id == entry_id for entry in entries)

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="search_hit"
            )
        )
    finally:
        run(backend.close())

    target_ids = [signal.target_id for signal in signals]
    assert entry_id in target_ids
    matched = next(signal for signal in signals if signal.target_id == entry_id)
    assert matched.target_kind == "memory_entry"
    assert matched.context == {"query": "SQLite FTS5"}


# --- 4. confirmed ----------------------------------------------------------


def test_confirmed_signal_emitted_on_auto_confirm(data_dir: Path) -> None:
    project_name = "sig-confirmed"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name=project_name,
            category="decision",
            content=(
                "We standardised on SQLite + sqlite-utils for all structured "
                "stores because the project is local-first and benefits from "
                "a zero-config embedded database."
            ),
            confidence=0.9,
            source="obs_abc123",
            status="pending",
        )
        entry_id = run(backend.structured_store.save_memory_entry(entry))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        assert summary.auto_confirmed >= 1

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="confirmed"
            )
        )
    finally:
        run(backend.close())

    target_ids = [signal.target_id for signal in signals]
    assert entry_id in target_ids
    matched = next(signal for signal in signals if signal.target_id == entry_id)
    assert matched.target_kind == "memory_entry"
    assert matched.context is not None
    assert matched.context.get("evidence_id") == "obs_abc123"


# --- 5. rejected -----------------------------------------------------------


def test_rejected_signal_emitted_on_auto_reject(data_dir: Path) -> None:
    project_name = "sig-rejected"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name=project_name,
            category="decision",
            content=(
                "Always write good code and follow best practices when "
                "designing the public API surface for downstream consumers."
            ),
            confidence=0.9,
            source="obs_noise",
            status="pending",
        )
        entry_id = run(backend.structured_store.save_memory_entry(entry))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        assert summary.auto_rejected >= 1

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="rejected"
            )
        )
    finally:
        run(backend.close())

    target_ids = [signal.target_id for signal in signals]
    assert entry_id in target_ids
    matched = next(signal for signal in signals if signal.target_id == entry_id)
    assert matched.target_kind == "memory_entry"


# --- 5b. rejected for rule_candidate maps to target_kind="candidate" ------


def test_rejected_signal_for_rule_candidate_uses_candidate_target_kind(
    data_dir: Path,
) -> None:
    project_name = "sig-rejected-rule"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        rule = RuleCandidate(
            project_name=project_name,
            session_id="sess-noise",
            pattern="Write good code and follow best practices on every PR.",
            trigger="When working on the codebase",
            examples=["example 1"],
            confidence=0.9,
            status="pending",
        )
        rule_id = run(backend.structured_store.save_rule_candidate(rule))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        assert summary.auto_rejected >= 1

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="rejected", target_kind="candidate"
            )
        )
    finally:
        run(backend.close())

    assert any(signal.target_id == rule_id for signal in signals)


# --- 6. skill_result_success / skill_result_failure -----------------------


def test_skill_result_signals_emitted_via_mcp_tool(data_dir: Path) -> None:
    project_name = "sig-skill"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        skill = _seed_skill(backend, project_name)

        mcp_server.set_backend_override(backend)
        try:
            success_payload = mcp_server.tool_record_skill_result(skill.id, True)
            failure_payload = mcp_server.tool_record_skill_result(skill.id, False)
        finally:
            mcp_server.set_backend_override(None)

        assert success_payload["success"] is True
        assert failure_payload["success"] is True

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, target_kind="skill"
            )
        )
    finally:
        run(backend.close())

    by_type = {signal.signal_type: signal for signal in signals}
    assert "skill_result_success" in by_type
    assert "skill_result_failure" in by_type
    assert by_type["skill_result_success"].target_id == skill.id
    assert by_type["skill_result_failure"].target_id == skill.id
    # The recorded value mirrors the running success_rate so selectors
    # can sort by trend.
    assert by_type["skill_result_success"].value == 1.0
    assert by_type["skill_result_failure"].value == 0.5


# --- 7. supersede_completed ------------------------------------------------


def test_supersede_completed_signal_emitted_via_mcp_tool(data_dir: Path) -> None:
    project_name = "sig-supersede"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        old_rule_id = _seed_confirmed_rule(backend, project_name, rule_id="rule-old")
        new_rule_id = _seed_confirmed_rule(backend, project_name, rule_id="rule-new")

        candidate = SupersedeCandidate(
            project_name=project_name,
            target_type="confirmed_rule",
            target_id=old_rule_id,
            replacement_type="confirmed_rule",
            replacement_id=new_rule_id,
            reason="Replacement after framework upgrade.",
            evidence="The new rule reflects the upgraded framework.",
            source="manual",
        )
        run(backend.structured_store.save_supersede_candidate(candidate))

        mcp_server.set_backend_override(backend)
        try:
            payload = mcp_server.tool_confirm_supersede(candidate.id)
        finally:
            mcp_server.set_backend_override(None)

        assert payload["success"] is True

        signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="supersede_completed"
            )
        )
    finally:
        run(backend.close())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.target_kind == "supersede"
    assert signal.target_id == candidate.id
    assert signal.context == {
        "target_type": "confirmed_rule",
        "target_id": old_rule_id,
        "replacement_type": "confirmed_rule",
        "replacement_id": new_rule_id,
    }


# --- 8. resilience: signal write failure must not block primary mutation --


def test_signal_write_failure_does_not_block_primary_mutation(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Auto-review must still flip candidate status when the signal table errors."""
    project_name = "sig-resilience"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name=project_name,
            category="decision",
            content=(
                "We standardised on SQLite + sqlite-utils for all structured "
                "stores because the project is local-first and benefits from "
                "a zero-config embedded database."
            ),
            confidence=0.9,
            source="obs_resilience",
            status="pending",
        )
        entry_id = run(backend.structured_store.save_memory_entry(entry))

        async def _boom(self, signal):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated signal-table failure")

        monkeypatch.setattr(
            LocalStructuredStore,
            "save_retrieval_signal",
            _boom,
        )

        with caplog.at_level(
            logging.ERROR, logger="harness_mem.commands.retrieval_signals"
        ):
            summary = run(
                auto_review_candidates(
                    backend, project_name=project_name, apply=True
                )
            )

        # (a) primary mutation still succeeded — candidate flipped to accepted.
        assert summary.auto_confirmed >= 1
        accepted = run(
            backend.structured_store.list_memory_entries(
                project_name, status="accepted"
            )
        )
        assert any(item.id == entry_id for item in accepted)

        # (b) zero rows in the signal table.
        signals = run(
            backend.structured_store.query_retrieval_signals(project_name)
        )
        assert signals == []

        # (c) failure was logged via the helper logger.
        assert any(
            "Failed to record retrieval signal" in record.message
            for record in caplog.records
        ), "expected record_retrieval_signal to log on save failure"
    finally:
        run(backend.close())
