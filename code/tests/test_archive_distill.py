from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.archive_distill import (
    inventory_codex_archives,
    print_archive_distill_result,
    run_archive_distill_batch,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.session_notes import materialize_session_note


def _write_archive(
    root: Path,
    workspace: Path,
    session_id: str,
    *,
    user_message: str = "Always run the related tests for small changes.",
) -> Path:
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
                "message": user_message,
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


def _write_empty_archive(
    root: Path,
    workspace: Path,
    session_id: str,
) -> Path:
    """Write a real host event log with no user/assistant conversation."""

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
            "type": "turn_context",
            "payload": {
                "turn_id": "host-turn",
                "current_date": "2026-08-13",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "host-turn",
                "type": "function_call",
                "name": "harness_mem_hook",
                "arguments": "{}",
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(root: Path, *, enabled: bool, require_answer_packet: bool = True) -> None:
    root.joinpath(".harness-mem.toml").write_text(
        "[archive_distill]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        "order = \"oldest_first\"\n"
        "project_scope = \"detected\"\n"
        "unresolved_project = \"defer\"\n"
        f"require_answer_packet = {'true' if require_answer_packet else 'false'}\n"
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
        config=MergedConfig(archive_distill_project_scope="detected"),
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
    (control / ".harness-mem.toml").write_text(
        '[archive_distill]\nproject_scope = "all"\n', encoding="utf-8"
    )
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


@pytest.mark.parametrize("project_scope", ["current", "all", "detected"])
def test_archive_terminal_statistics_respect_project_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_scope: str,
) -> None:
    from harness_mem.commands.archive_distill import _source_revision

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    control = tmp_path / "current" / "shared-name"
    other = tmp_path / "other" / "shared-name"
    control.mkdir(parents=True)
    other.mkdir(parents=True)
    control.joinpath(".harness-mem.toml").write_text(
        f'[archive_distill]\nproject_scope = "{project_scope}"\n',
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    data = tmp_path / "data"
    entries = {}
    # Both projects deliberately have the same name. A source revision and
    # project name alone cannot bind a terminal record to the current root.
    live_records = [
        ("current-completed", control, control / ".." / control.name, "verified_completed"),
        ("current-quarantined", control, control, "quarantined"),
        ("wrong-root-live", control, other, "verified_completed"),
        ("missing-root-live", control, None, "quarantined"),
        ("other-live", other, other, "verified_completed"),
        ("unresolved-live", tmp_path / "missing", None, "quarantined"),
    ]
    for session_id, workspace, entry_root, disposition in live_records:
        source = _write_archive(archive, workspace, session_id)
        entries[session_id] = {
            "project_name": control.name,
            "project_root": str(entry_root) if entry_root is not None else None,
            "source_revision": _source_revision(source),
            "disposition": disposition,
        }
    _write_archive(archive, control, "current-pending")
    # Deleted sources must use the stored full root; they cannot rely on the
    # live inventory for attribution. Keep both terminal dispositions covered.
    for label, entry_root in [("current", control), ("other", other), ("unowned", None)]:
        for disposition in ["verified_completed", "quarantined"]:
            session_id = f"{label}-deleted-{disposition}"
            source = _write_archive(archive, entry_root or control, session_id)
            entries[session_id] = {
                "project_name": control.name,
                "source_revision": _source_revision(source),
                "disposition": disposition,
            }
            if entry_root is not None:
                entries[session_id]["project_root"] = str(entry_root)
            source.unlink()
    terminal = data / "archive_distill" / "terminal_index.json"
    terminal.parent.mkdir(parents=True)
    terminal.write_text(json.dumps({"version": 1, "sessions": entries}), encoding="utf-8")
    original_index = terminal.read_bytes()

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=data,
        )
    )

    if project_scope == "current":
        assert {row["session_id"] for row in result["selected"]} == {
            "wrong-root-live", "missing-root-live", "current-pending",
        }
        expected_terminal = (1, 1, 3, 0)
        expected_lifecycle = {
            "verified_completed": 2,
            "quarantined": 2,
            "pending_eligible": 3,
            "deferred_unresolved": 0,
            "excluded": 0,
            "source_deleted_after_verified": 1,
            "total": 7,
            "conserved": True,
        }
    else:
        assert [row["session_id"] for row in result["selected"]] == ["current-pending"]
        expected_terminal = (3, 2, 1, 0)
        expected_lifecycle = {
            "verified_completed": 6,
            "quarantined": 6,
            "pending_eligible": 1,
            "deferred_unresolved": 1,
            "excluded": 0,
            "source_deleted_after_verified": 3,
            "total": 14,
            "conserved": True,
        }
    assert tuple(
        result["terminal"][key]
        for key in ("verified_completed", "quarantined", "pending_eligible", "excluded")
    ) == expected_terminal
    assert result["terminal"]["inventory_total"] == (5 if project_scope == "current" else 7)
    assert result["terminal"]["total"] == (5 if project_scope == "current" else 7)
    assert result["inventory"]["sessions_found"] == 7
    assert result["inventory"]["unresolved"] == 1
    assert result["terminal"]["conserved"] is True
    assert result["lifecycle_terminal"] == expected_lifecycle
    assert terminal.read_bytes() == original_index
    assert not (data / "archive_distill" / "daily").exists()


@pytest.mark.parametrize("root_kind", ["missing", "empty", "relative", "invalid", "non_string"])
def test_archive_current_scope_requires_absolute_terminal_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_kind: str,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    control = tmp_path / "project"
    control.mkdir()
    monkeypatch.chdir(control)
    control.joinpath(".harness-mem.toml").write_text(
        '[archive_distill]\nproject_scope = "current"\n', encoding="utf-8"
    )
    entry = {"project_name": control.name, "disposition": "verified_completed"}
    roots = {"empty": "", "relative": ".", "invalid": str(control) + "\0", "non_string": 42}
    if root_kind != "missing":
        entry["project_root"] = roots[root_kind]
    data = tmp_path / "data"
    terminal = data / "archive_distill" / "terminal_index.json"
    terminal.parent.mkdir(parents=True)
    terminal.write_text(
        json.dumps({"version": 1, "sessions": {"unbound-deleted": entry}}),
        encoding="utf-8",
    )

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=tmp_path / "archives",
            data_dir=data,
        )
    )

    assert result["selected"] == []
    assert result["lifecycle_terminal"] == {
        "verified_completed": 0,
        "quarantined": 0,
        "pending_eligible": 0,
        "deferred_unresolved": 0,
        "excluded": 0,
        "source_deleted_after_verified": 0,
        "total": 0,
        "conserved": True,
    }


def test_archive_run_limits_can_be_overridden_without_editing_config(tmp_path: Path) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    (control / ".harness-mem.toml").write_text(
        '[archive_distill]\nproject_scope = "all"\n', encoding="utf-8"
    )
    project.mkdir()
    archive = tmp_path / "archives"
    for index in range(4):
        _write_archive(archive, project, f"session-{index}")

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=tmp_path / "data",
            batch_size=4,
        )
    )

    assert result["policy"]["batch_size"] == 4
    assert len(result["selected"]) == 4


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
    (control / ".harness-mem.toml").write_text(
        '[archive_distill]\nproject_scope = "all"\n', encoding="utf-8"
    )
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
    capsys,
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
    _write_archive(
        archive,
        project,
        "session-a",
        user_message=(
            "<private>never persists</private> Always run the related tests "
            "for small changes."
        ),
    )

    provider_calls = 0

    def fake_batch(backend, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
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
        candidate = RuleCandidate(
            project_name=job.project_name,
            session_id=job.session_id,
            pattern="Small changes require related tests.",
            trigger="Related test rule",
            confidence=0.95,
            status="auto_confirmed",
            distill_job_id=job.id,
        )
        asyncio.run(backend.structured_store.save_rule_candidate(candidate))
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
            output_candidate_ids=[candidate.id],
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
            source_cleanup_status="retained",
        )
        current = KnowledgeEntry(
            project_name=project.name,
            module_path=["Archive processing"],
            title=candidate.trigger,
            statement=candidate.pattern,
            verified_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        knowledge_candidate = KnowledgeCandidate(
            id="candidate-session-reverify",
            project_name=project.name,
            candidate_type="rule",
            statement=candidate.pattern,
        )
        decision = AssimilationDecision(
            id="mutation-session-reverify",
            project_name=project.name,
            candidate_id=knowledge_candidate.id,
            disposition="add",
            canonical_truth_ids=[current.id],
            reason="Archive re-verification fixture.",
        )
        store = backend.structured_store.knowledge_store
        asyncio.run(store.save_candidate(knowledge_candidate))
        asyncio.run(
            store.apply_current_change(
                candidate_before=knowledge_candidate,
                candidate_after=knowledge_candidate.model_copy(
                    update={"status": "assimilated"}
                ),
                decision=decision,
                added_entries=[current],
                predecessor_entries=[],
                source_refs_by_entry={
                    current.id: [
                        ProjectKnowledgeSourceRef(
                            label="Archived Codex session",
                            target=f"session:{job.source_id}",
                            kind="transcript",
                        )
                    ]
                },
            )
        )
        asyncio.run(store.cleanup_candidate(knowledge_candidate.id))
        stored = backend.transcript_store.get_distill_job(job.id)
        assert stored is not None
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
            verify=True,
        )
    )

    assert result["success"] is True
    assert result["completed"] == 1
    outcome = result["outcomes"][0]
    assert outcome["answer_packet"]["answer_status"] == "ANSWERED"
    assert outcome["promoted_items"][0]["fact"] == "Small changes require related tests."
    assert outcome["warnings"] == []
    assert outcome["execution"] == "provider_executed"
    note_text = Path(outcome["note"]["path"]).read_text(encoding="utf-8")
    assert "结果校验" in note_text
    assert "已写入长期记忆" in note_text
    assert "知识类型：" not in note_text
    assert "知识分类：" not in note_text
    assert "（rule / testing）" not in note_text

    print_archive_distill_result(result, as_json=False)
    rendered = capsys.readouterr().out
    assert "Memory verification" in rendered
    assert "Memory: saved" in rendered
    assert "(rule / testing)" not in rendered
    ledger = json.loads(Path(result["ledger"]).read_text(encoding="utf-8"))
    assert ledger["processed_session_ids"] == ["session-a"]
    assert provider_calls == 1

    repeated = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=tmp_path / "data",
            now=now + timedelta(days=1),
            verify=True,
        )
    )
    assert repeated["selected"] == []
    assert repeated["outcomes"] == []
    assert repeated["terminal"]["verified_completed"] == 1
    assert repeated["terminal"]["pending_eligible"] == 0
    assert repeated["terminal"]["conserved"] is True
    assert repeated["lifecycle_terminal"]["verified_completed"] == 1
    assert repeated["lifecycle_terminal"]["pending_eligible"] == 0
    assert repeated["lifecycle_terminal"]["conserved"] is True
    assert provider_calls == 1


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
        "[distill]\nauto = true\n",
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


def test_archive_apply_verify_accepts_missing_answer_packet_when_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    _write_config(control, enabled=True, require_answer_packet=False)
    project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = true\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    _write_archive(archive, project, "session-answer-packet-off")

    def fake_batch(backend, **kwargs):
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
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
                "session_summary": "The user asked for a direct verification probe.",
                "final_user_request": "Run no durable work.",
                "final_outcome": "No durable memory was produced.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "not_applicable",
                "promotion_decision": "no_promotion",
            },
        )
        packet = {
            "answer_status": "NOT_APPLICABLE",
            "question": "Run direct probe without answer packet in output.",
            "core_conclusion": "No durable memory was produced.",
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
    assert result["outcomes"][0]["answer_packet"] is None
    assert verified["checks"]["job_persisted"] is True
    assert Path(result["run_receipt"]).is_file()


def test_archive_completed_job_is_reverified_without_provider_replay(
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
    source = _write_archive(archive, project, "session-reverify")
    data = tmp_path / "data"

    from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data)
    asyncio.run(backend.init())
    try:
        synced = asyncio.run(
            CodexArchiveAdapter(backend, archive_dir=archive).sync_session(
                source,
                "session-reverify",
                project.name,
                project_root=project,
            )
        )
        job = backend.transcript_store.get_distill_job(str(synced.distill_job_id))
        assert job is not None
        owner = "reverify-test"
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            job.id, lease_owner=owner, limit=100
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                job.id, chunk.id, lease_owner=owner, result={"summary": "read"}
            )
        candidate = RuleCandidate(
            project_name=project.name,
            session_id="session-reverify",
            pattern="Persist verified archive terminal states.",
            trigger="After archive distill verification",
            confidence=0.95,
            status="auto_confirmed",
            distill_job_id=job.id,
        )
        asyncio.run(backend.structured_store.save_rule_candidate(candidate))
        backend.transcript_store.finalize_distill_job(
            job.id,
            semantic_review={
                "session_summary": "The user requested durable archive completion tracking.",
                "final_user_request": "Persist verified terminal states.",
                "final_outcome": "The durable rule was accepted.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "promote",
            },
            output_candidate_ids=[candidate.id],
        )
        packet = {
            "answer_status": "ANSWERED",
            "question": "How should archive completion be tracked?",
            "core_conclusion": candidate.pattern,
            "evidence_basis": ["user_statement"],
            "verified_at": "2026-08-13T00:00:00+00:00",
            "promotion_status": "promoted",
            "promoted_items": [{
                "title": candidate.trigger,
                "fact": candidate.pattern,
                "kind": "rule",
                "category": "rule",
            }],
            "destination_project": project.name,
            "knowledge_kind": ["rule"],
            "knowledge_category": ["rule"],
        }
        backend.transcript_store.record_distill_completion_outcome(
            job.id,
            disposition="promoted",
            reason_codes=["durable_memory_promoted"],
            promotion_summary={"promoted": 1, "answer_packet": packet},
            source_cleanup_status="retained",
        )
        current = KnowledgeEntry(
            project_name=project.name,
            module_path=["Archive processing"],
            title=candidate.trigger,
            statement=candidate.pattern,
            verified_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        knowledge_candidate = KnowledgeCandidate(
            id="candidate-completed-reverify",
            project_name=project.name,
            candidate_type="rule",
            statement=candidate.pattern,
        )
        decision = AssimilationDecision(
            id="mutation-completed-reverify",
            project_name=project.name,
            candidate_id=knowledge_candidate.id,
            disposition="add",
            canonical_truth_ids=[current.id],
            reason="Archive re-verification fixture.",
        )
        store = backend.structured_store.knowledge_store
        asyncio.run(store.save_candidate(knowledge_candidate))
        asyncio.run(
            store.apply_current_change(
                candidate_before=knowledge_candidate,
                candidate_after=knowledge_candidate.model_copy(
                    update={"status": "assimilated"}
                ),
                decision=decision,
                added_entries=[current],
                predecessor_entries=[],
                source_refs_by_entry={
                    current.id: [
                        ProjectKnowledgeSourceRef(
                            label="Archived Codex session",
                            target=f"session:{job.source_id}",
                            kind="transcript",
                        )
                    ]
                },
            )
        )
        asyncio.run(store.cleanup_candidate(knowledge_candidate.id))
    finally:
        asyncio.run(backend.close())

    def fail_if_provider_runs(*_args, **_kwargs):
        raise AssertionError("completed job must be reverified without provider")

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        fail_if_provider_runs,
    )
    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            notes_dir=tmp_path / "notes",
        )
    )

    assert result["success"] is True
    assert result["verified_completed"] == 1
    assert result["outcomes"][0]["execution"] == "completed_job_reverified"
    assert result["outcomes"][0]["provider"]["total_tokens"] == 0
    assert result["verification"]["outcomes"][0]["retrieval"]["status"] == "passed"


def test_archive_verification_rejects_legacy_relation_without_current_knowledge(
    tmp_path: Path,
) -> None:
    from harness_mem.commands.archive_distill import _verify_promoted_items
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        relation = RelationFact(
            project_name="demo",
            source_entity="canonical_store",
            relation_type="provides durable truth independently of",
            target_entity="derived indexes",
            confidence=0.95,
            status="provisional",
            evidence="Verified user statement.",
            source="processed_source_pruned",
        )
        asyncio.run(backend.structured_store.save_relation_fact(relation))
        result = asyncio.run(
            _verify_promoted_items(
                backend,
                project_name="demo",
                job_id="pruned-job",
                promoted_items=[{
                    "title": "canonical_store relation",
                    "fact": (
                        "canonical_store provides durable truth independently of "
                        "derived indexes"
                    ),
                    "kind": "relation",
                    "category": relation.relation_type,
                }],
            )
        )
    finally:
        asyncio.run(backend.close())

    assert result["status"] == "partial"
    assert result["items"][0]["retrieval_mode"] == "normal_current_search"
    assert result["items"][0]["retrieved"] is False


def test_archive_repair_only_accepts_new_completed_job_for_same_revision(
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
    data = tmp_path / "data"
    source = _write_archive(archive, project, "session-deleted-repair")
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "Always run the related tests for small changes.",
            "Return exactly: OK",
        ),
        encoding="utf-8",
    )
    first = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            provider=None,
            notes_dir=tmp_path / "notes",
        )
    )
    # Replace the successful terminal admission with a historical quarantined
    # partial receipt. The completed job and Note remain the repair authority
    # after source removal, but the terminal entry prevents a normal batch
    # retry and must therefore be explicitly repairable.
    terminal = Path(str(first["terminal_index"]))
    index = json.loads(terminal.read_text(encoding="utf-8"))
    entry = index["sessions"]["session-deleted-repair"]
    entry["disposition"] = "quarantined"
    entry["reason"] = "deferred"
    entry["failed_checks"] = ["answer_packet_persisted"]
    terminal.write_text(json.dumps(index), encoding="utf-8")
    receipt_path = Path(str(first["run_receipt"]))
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["success"] = False
    payload["verification"]["status"] = "partial"
    payload["outcomes"][0]["status"] = "deferred"
    payload["outcomes"][0]["reason"] = "historical semantic review still pending"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data)
    asyncio.run(backend.init())
    old_job = backend.transcript_store.get_distill_job(entry["distill_job_id"])
    assert old_job is not None
    corrected_job = backend.transcript_store.enqueue_distill_job(
        old_job.source_id,
        pipeline_version="lossless-distill-v1-current-knowledge-v1",
    )
    for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
        corrected_job.id,
        lease_owner="corrected-review",
        limit=1000,
    ):
        backend.transcript_store.checkpoint_distill_chunk(
            corrected_job.id,
            chunk.id,
            lease_owner="corrected-review",
            result={"summary": "rechecked"},
        )
    corrected_job = backend.transcript_store.finalize_distill_job(
        corrected_job.id,
        semantic_review=old_job.semantic_review,
        output_candidate_ids=old_job.output_candidate_ids,
    )
    corrected_job = backend.transcript_store.record_distill_completion_outcome(
        corrected_job.id,
        disposition=old_job.completion_disposition,
        reason_codes=old_job.completion_reason_codes,
        promotion_summary=old_job.promotion_summary,
        source_cleanup_status="retained",
    )
    materialize_session_note(corrected_job, notes_dir=tmp_path / "notes")
    asyncio.run(backend.close())
    source.unlink(missing_ok=True)

    def fail_if_provider_runs(*_args, **_kwargs):
        raise AssertionError("repair-only must not run provider")

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        fail_if_provider_runs,
    )
    repaired = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            repair_only=True,
            archive_dir=archive,
            data_dir=data,
            notes_dir=tmp_path / "notes",
        )
    )

    assert repaired["selected"] == []
    assert repaired["partial_receipt_repair"]["count"] == 1
    index = json.loads(terminal.read_text(encoding="utf-8"))
    entry = index["sessions"]["session-deleted-repair"]
    assert entry["disposition"] == "verified_completed"
    assert entry["distill_job_id"] == corrected_job.id
    assert entry["repaired_from_partial_receipt"] is True
    assert entry["repair_kind"] == "completed_job_after_deferred_receipt"


def test_archive_repair_only_current_scope_does_not_repair_another_project(
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    other_project = tmp_path / "other-project"
    control.mkdir()
    other_project.mkdir()
    _write_config(control, enabled=True)
    other_project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = true\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    source = _write_archive(archive, other_project, "session-other-project")
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "Always run the related tests for small changes.",
            "Return exactly: OK",
        ),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    notes = tmp_path / "notes"
    first = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            provider=None,
            notes_dir=notes,
        )
    )
    terminal = Path(str(first["terminal_index"]))
    index = json.loads(terminal.read_text(encoding="utf-8"))
    entry = index["sessions"]["session-other-project"]
    entry["disposition"] = "quarantined"
    entry["reason"] = (
        "codex provider decision could not be bound to local evidence: "
        "point cites unavailable exchange 2"
    )
    terminal.write_text(json.dumps(index), encoding="utf-8")
    control.joinpath(".harness-mem.toml").write_text(
        "[archive_distill]\n"
        "enabled = true\n"
        "order = \"oldest_first\"\n"
        "project_scope = \"current\"\n"
        "unresolved_project = \"defer\"\n"
        "require_answer_packet = true\n",
        encoding="utf-8",
    )

    repaired = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            repair_only=True,
            archive_dir=archive,
            data_dir=data,
            notes_dir=notes,
        )
    )

    assert repaired["selected"] == []
    assert repaired["partial_receipt_repair"]["count"] == 0
    index = json.loads(terminal.read_text(encoding="utf-8"))
    assert index["sessions"]["session-other-project"]["disposition"] == "quarantined"


def test_archive_retries_are_not_capped_by_attempt_count(
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
    _write_archive(archive, project, "session-bounded-retry")
    calls = 0

    def always_deferred(backend, **kwargs):
        nonlocal calls
        calls += 1
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
        assert job is not None
        return {
            "success": False,
            "state": "deferred",
            "outcomes": [{
                "job_id": job.id,
                "session_id": job.session_id,
                "status": "deferred",
                "provider": {"total_tokens": 0, "duration_seconds": 0.0},
            }],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        always_deferred,
    )
    data = tmp_path / "data"
    first = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            now=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
    )
    second = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            now=datetime(2026, 8, 14, tzinfo=timezone.utc),
        )
    )
    third = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=data,
            now=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
    )

    assert first["quarantined"] == 0
    assert second["quarantined"] == 0
    assert len(third["selected"]) == 1
    assert third["terminal"]["quarantined"] == 0
    assert calls == 2
    index = json.loads(Path(second["terminal_index"]).read_text(encoding="utf-8"))
    assert index["attempts"]["session-bounded-retry"]["count"] == 2
    assert "session-bounded-retry" not in index["sessions"]


def test_archive_stops_batch_on_systemic_worker_error_and_preserves_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
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
    for index in range(3):
        _write_archive(archive, project, f"session-system-{index}")
    calls = 0

    def auth_failure(backend, **kwargs):
        nonlocal calls
        calls += 1
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
        assert job is not None
        return {
            "success": False,
            "state": "deferred",
            "outcomes": [
                {
                    "job_id": job.id,
                    "session_id": job.session_id,
                    "status": "deferred",
                    "error": {
                        "kind": "auth_invalid",
                        "message": "Codex CLI login expired.",
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        auth_failure,
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

    assert calls == 1
    assert len(result["selected"]) == 1
    assert len(result["outcomes"]) == 1
    assert result["stopped_early"] is True
    assert result["stop_error"] == {
        "kind": "auth_invalid",
        "message": "Codex CLI login expired.",
    }
    assert result["outcomes"][0]["error"] == result["stop_error"]
    assert result["outcomes"][0]["reason"] == "Codex CLI login expired."
    assert "answer_packet_missing" not in result["outcomes"][0]["warnings"]

    print_archive_distill_result(result, as_json=False)
    rendered = capsys.readouterr().out
    assert "Error: auth_invalid: Codex CLI login expired." in rendered


def test_archive_keeps_one_session_evidence_reference_error_retryable(
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
    for index in range(3):
        _write_archive(archive, project, f"session-evidence-{index}")
    calls = 0
    message = (
        "provider correction failed candidate validation: "
        "candidate[0] cited an unavailable exchange index"
    )

    def invalid_evidence_reference(backend, **kwargs):
        nonlocal calls
        calls += 1
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
        assert job is not None
        backend.transcript_store.defer_distill_job(
            job.id,
            error=f"unrecoverable: {message}",
        )
        return {
            "success": False,
            "state": "deferred",
            "outcomes": [
                {
                    "job_id": job.id,
                    "session_id": job.session_id,
                    "status": "deferred",
                }
            ],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        invalid_evidence_reference,
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

    assert calls == 3
    assert len(result["outcomes"]) == 3
    assert result["stopped_early"] is False
    assert all(
        item["error"] == {"kind": "unrecoverable", "message": message}
        for item in result["outcomes"]
    )
    assert all("answer_packet_missing" not in item["warnings"] for item in result["outcomes"])
    assert result["quarantined"] == 0
    ledger = json.loads(Path(result["ledger"]).read_text(encoding="utf-8"))
    assert len(ledger["retryable_session_ids"]) == 3


def test_archive_retry_backoff_does_not_consume_an_attempt(tmp_path: Path, monkeypatch) -> None:
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
    _write_archive(archive, project, "session-backoff")
    calls = 0

    def defer_after_structural_work(backend, **kwargs):
        nonlocal calls
        calls += 1
        job = backend.transcript_store.get_distill_job(kwargs["preferred_job_id"])
        assert job is not None
        owner = "backoff-test"
        for chunk, _checkpoint in backend.transcript_store.claim_distill_chunks(
            job.id, lease_owner=owner, limit=100
        ):
            backend.transcript_store.checkpoint_distill_chunk(
                job.id,
                chunk.id,
                lease_owner=owner,
                result={"summary": "read"},
            )
        backend.transcript_store.defer_distill_job(job.id, error="provider timeout")
        return {
            "success": False,
            "state": "deferred",
            "outcomes": [
                {
                    "job_id": job.id,
                    "session_id": job.session_id,
                    "status": "deferred",
                    "provider": {"total_tokens": 0, "duration_seconds": 0.0},
                }
            ],
        }

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        defer_after_structural_work,
    )
    data = tmp_path / "data"
    current = datetime.now(timezone.utc)
    first = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=data,
            now=current,
        )
    )
    second = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            archive_dir=archive,
            data_dir=data,
            now=current + timedelta(seconds=1),
        )
    )

    assert calls == 1
    assert second["outcomes"][0]["reason"] == "retry_backoff"
    assert second["quarantined"] == 0
    index = json.loads(Path(second["terminal_index"]).read_text(encoding="utf-8"))
    assert index["attempts"]["session-backoff"]["count"] == 1
    assert first["terminal"]["pending_eligible"] == 1


def test_archive_new_source_revision_resets_attempt_budget(
    tmp_path: Path,
) -> None:
    from harness_mem.transcript_chunking import transcript_bytes_revision

    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    (control / ".harness-mem.toml").write_text(
        '[archive_distill]\nproject_scope = "all"\n', encoding="utf-8"
    )
    project.mkdir()
    archive = tmp_path / "archives"
    source = _write_archive(archive, project, "session-revised")
    data = tmp_path / "data"
    terminal = data / "archive_distill" / "terminal_index.json"
    terminal.parent.mkdir(parents=True)
    terminal.write_text(
        json.dumps({
            "version": 1,
            "sessions": {},
            "attempts": {
                "session-revised": {
                    "session_id": "session-revised",
                    "source_revision": "sha256:" + "0" * 64,
                    "count": 2,
                }
            },
        }),
        encoding="utf-8",
    )
    day = data / "archive_distill" / "daily" / "2026-08-13.json"
    day.parent.mkdir(parents=True)
    day.write_text(
        json.dumps({
            "day": "2026-08-13",
            "attempted_session_ids": ["session-revised"],
            "attempt_counts": {"session-revised": 2},
            "processed_session_ids": [],
            "runs": [],
        }),
        encoding="utf-8",
    )

    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=data,
            now=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        )
    )

    assert result["selected"][0]["session_id"] == "session-revised"
    assert transcript_bytes_revision(source.read_bytes()) != "sha256:" + "0" * 64


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
        "[distill]\nauto = true\n",
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


def test_empty_archive_has_verified_terminal_without_job_note_or_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness_mem.commands.archive_distill import _verify_archive_distill_run
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    control = tmp_path / "control"
    project = tmp_path / "project"
    control.mkdir()
    project.mkdir()
    _write_config(control, enabled=True)
    # Empty classification is deterministic and does not require model
    # authorization, but it remains inside the explicitly enabled archive run.
    project.joinpath(".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = false\n",
        encoding="utf-8",
    )
    archive = tmp_path / "archives"
    source = _write_empty_archive(archive, project, "session-empty")
    data = tmp_path / "data"
    notes = tmp_path / "notes"

    def fail_if_provider_runs(*_args, **_kwargs):
        raise AssertionError("empty archive must not run a semantic provider")

    monkeypatch.setattr(
        "harness_mem.commands.archive_distill.run_autonomous_distill_batch",
        fail_if_provider_runs,
    )
    result = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=True,
            verify=True,
            archive_dir=archive,
            data_dir=data,
            notes_dir=notes,
            provider=object(),
        )
    )

    assert result["success"] is True
    assert result["completed"] == 1
    assert result["deferred"] == 0
    outcome = result["outcomes"][0]
    assert outcome["classification"] == "empty_archive"
    assert outcome["execution"] == "deterministic_empty"
    assert outcome["distill_job_id"] is None
    assert outcome["note"] is None
    assert outcome["promoted_items"] == []
    assert outcome["provider"] == {
        "used": False,
        "total_tokens": 0,
        "duration_seconds": 0.0,
    }
    assert outcome["knowledge_after"] == outcome["knowledge_before"]
    assert source.is_file()
    assert not notes.exists()
    verified = result["verification"]["outcomes"][0]
    assert verified["status"] == "passed"
    assert verified["checks"] == {
        "source_exists": True,
        "source_revision_matches": True,
        "no_user_or_assistant_messages": True,
        "no_job_created": True,
        "no_note_created": True,
        "knowledge_unchanged": True,
    }

    backend = LocalMemoryBackend(data)
    asyncio.run(backend.init())
    try:
        assert backend.transcript_store.list_distill_jobs(
            project_name=project.name,
            limit=100,
        ) == []
        assert asyncio.run(
            backend.structured_store.knowledge_store.list_entries(project.name)
        ) == []

        # A later archive in the same batch may legitimately change current
        # knowledge. Re-verifying the earlier empty result must stay bound to
        # its immediate before/after snapshots instead of blaming that later
        # write on the empty archive.
        later_entry = KnowledgeEntry(
            project_name=project.name,
            module_path=["Archive processing"],
            title="Later archive result",
            statement="A later non-empty archive produced this current knowledge.",
            verified_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        later_candidate = KnowledgeCandidate(
            id="candidate-after-empty",
            project_name=project.name,
            candidate_type="memory",
            statement=later_entry.statement,
        )
        later_decision = AssimilationDecision(
            id="mutation-after-empty",
            project_name=project.name,
            candidate_id=later_candidate.id,
            disposition="add",
            canonical_truth_ids=[later_entry.id],
            reason="Exercise mixed empty and non-empty batch verification.",
        )
        store = backend.structured_store.knowledge_store
        asyncio.run(store.save_candidate(later_candidate))
        asyncio.run(
            store.apply_current_change(
                candidate_before=later_candidate,
                candidate_after=later_candidate.model_copy(
                    update={"status": "assimilated"}
                ),
                decision=later_decision,
                added_entries=[later_entry],
                predecessor_entries=[],
                source_refs_by_entry={
                    later_entry.id: [
                        ProjectKnowledgeSourceRef(
                            label="Later archive",
                            target="session:later-archive",
                            kind="transcript",
                        )
                    ]
                },
            )
        )
        reverified = asyncio.run(
            _verify_archive_distill_run(backend, result=result)
        )
        assert reverified["status"] == "passed"
        assert reverified["outcomes"][0]["checks"]["knowledge_unchanged"] is True
        assert reverified["outcomes"][0]["current_knowledge"]["count"] == 1
    finally:
        asyncio.run(backend.close())

    repeated = asyncio.run(
        run_archive_distill_batch(
            control_root=control,
            apply=False,
            archive_dir=archive,
            data_dir=data,
        )
    )
    assert repeated["selected"] == []
    assert repeated["terminal"]["verified_completed"] == 1
    assert repeated["terminal"]["pending_eligible"] == 0
    assert repeated["terminal"]["inventory_total"] == 1
    assert repeated["terminal"]["conserved"] is True


def test_trivial_archive_provider_fails_closed_for_unexpected_assimilation() -> None:
    from harness_mem.autonomous.provider import ProviderError
    from harness_mem.commands.archive_distill import _TrivialArchiveProvider

    with pytest.raises(ProviderError, match="cannot perform semantic assimilation"):
        _TrivialArchiveProvider(
            "Return exactly: ARCHIVE_SMOKE_OK",
            source_revision="sha256:" + "0" * 64,
        ).assimilate(
            {},
            runtime_dir=Path.cwd(),
        )


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


@pytest.fixture
def completed_archive(tmp_path: Path, monkeypatch):
    """A quiet native-shaped archive with real isolated SQLite and no provider."""
    import os
    import time

    from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    root = tmp_path / "project"
    root.mkdir()
    archive = tmp_path / ".codex" / "archived_sessions"
    source = _write_archive(archive, root, "completed-replay")
    os.utime(source, (time.time() - 600,) * 2)
    data = tmp_path / "data"
    notes = tmp_path / "notes"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    config = MergedConfig(
        archive_distill_enabled=True,
        archive_distill_project_scope="current",
        distill_autonomous_enabled=True,
    )
    monkeypatch.setattr("harness_mem.commands.archive_distill.load_merged_config", lambda *_: config)

    def no_provider(*_args, **_kwargs):
        pytest.fail("completed replay must not invoke a provider")

    monkeypatch.setattr("harness_mem.commands.archive_distill.run_autonomous_distill_batch", no_provider)
    backend = LocalMemoryBackend(data)
    asyncio.run(backend.init())
    try:
        captured = asyncio.run(CodexArchiveAdapter(backend, archive_dir=archive).sync_session(
            source, "completed-replay", root.name, project_root=root,
        ))
        job_id = captured.distill_job_id
        for chunk, _ in backend.transcript_store.claim_distill_chunks(job_id, lease_owner="fixture", limit=None):
            backend.transcript_store.checkpoint_distill_chunk(
                job_id, chunk.id, lease_owner="fixture", result={"summary": "read"},
            )
        current = KnowledgeEntry(
            project_name=root.name, module_path=["Testing"], title="Related tests",
            statement="Always run the related tests for small changes.",
            verified_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )
        candidate = KnowledgeCandidate(project_name=root.name, candidate_type="rule", statement=current.statement)
        decision = AssimilationDecision(
            project_name=root.name, candidate_id=candidate.id, disposition="add",
            canonical_truth_ids=[current.id], reason="Isolated archive replay fixture.",
        )
        store = backend.structured_store.knowledge_store
        asyncio.run(store.save_candidate(candidate))
        asyncio.run(store.apply_current_change(
            candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision, added_entries=[current], predecessor_entries=[],
            source_refs_by_entry={current.id: [ProjectKnowledgeSourceRef(
                label="Isolated archived session", target=f"session:{captured.source.id}", kind="transcript",
            )]},
        ))
        asyncio.run(store.cleanup_candidate(candidate.id))
        backend.transcript_store.finalize_distill_job(job_id, semantic_review={
            "session_summary": "The user chose related tests as a reusable project testing rule.",
            "final_user_request": current.statement, "final_outcome": "The testing rule was saved.",
            "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
            "evidence_status": "answered", "promotion_decision": "promote",
        }, output_candidate_ids=[candidate.id])
        packet = {
            "answer_status": "ANSWERED", "question": "Which tests should run?",
            "core_conclusion": current.statement, "promotion_status": "promoted",
            "promoted_items": [{"title": current.title, "fact": current.statement, "kind": "rule", "category": "Testing"}],
            "destination_project": root.name,
        }
        job = backend.transcript_store.record_distill_completion_outcome(
            job_id, disposition="promoted", reason_codes=["durable_memory_promoted"],
            promotion_summary={"promoted": 1, "suggested": 1, "answer_packet": packet, "points": [{
                "candidate_id": candidate.id, "disposition": "add", "canonical_truth_ids": [current.id],
            }]}, source_cleanup_status="retained",
        )
    finally:
        asyncio.run(backend.close())

    def run():
        return asyncio.run(run_archive_distill_batch(
            control_root=root, apply=True, verify=True, archive_dir=archive, data_dir=data, notes_dir=notes,
        ))

    return {"root": root, "archive": archive, "source": source, "data": data,
            "notes": notes, "config": config, "job": job, "entry": current, "run": run}


@pytest.mark.parametrize("require_packet", [True, False])
def test_archive_replay_missing_current_keeps_source(completed_archive, monkeypatch, require_packet):
    from dataclasses import replace

    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    fixture = completed_archive
    config = replace(fixture["config"], archive_distill_require_answer_packet=require_packet)
    monkeypatch.setattr("harness_mem.commands.archive_distill.load_merged_config", lambda *_: config)
    backend = LocalMemoryBackend(fixture["data"])
    asyncio.run(backend.init())
    try:
        asyncio.run(backend.structured_store.knowledge_store.delete_current_entry(
            project_name="project", entry_id=fixture["entry"].id,
        ))
    finally:
        asyncio.run(backend.close())
    before = fixture["source"].read_bytes()
    result = fixture["run"]()
    assert fixture["source"].read_bytes() == before
    assert result["success"] is False
    assert result["completed"] == result["verified_completed"] == 0
    assert result["deferred"] == 1
    index = json.loads(Path(result["terminal_index"]).read_text(encoding="utf-8"))
    assert "completed-replay" not in index["sessions"]


def test_archive_replay_unremoved_predecessor_keeps_source(completed_archive):
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    fixture = completed_archive
    backend = LocalMemoryBackend(fixture["data"])
    asyncio.run(backend.init())
    try:
        old = KnowledgeEntry(
            project_name="project", module_path=["Testing"], title="Earlier testing rule",
            statement="Previously the project ran every test for all edits.",
            verified_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        )
        candidate = KnowledgeCandidate(project_name="project", candidate_type="rule", statement=old.statement)
        store = backend.structured_store.knowledge_store
        asyncio.run(store.save_candidate(candidate))
        asyncio.run(store.apply_current_change(
            candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=AssimilationDecision(project_name="project", candidate_id=candidate.id, disposition="add",
                                          canonical_truth_ids=[old.id], reason="Existing predecessor fixture."),
            added_entries=[old], predecessor_entries=[], source_refs_by_entry={old.id: [ProjectKnowledgeSourceRef(
                label="Isolated predecessor source", target=f"session:{fixture['job'].source_id}", kind="transcript",
            )]},
        ))
        asyncio.run(store.cleanup_candidate(candidate.id))
        job = fixture["job"]
        promotion = {**job.promotion_summary, "points": [{
            **job.promotion_summary["points"][0], "disposition": "replace", "replaced_truth_ids": [old.id],
        }]}
        backend.transcript_store.record_distill_completion_outcome(
            job.id, disposition="promoted", reason_codes=job.completion_reason_codes,
            promotion_summary=promotion, source_cleanup_status="retained",
        )
    finally:
        asyncio.run(backend.close())
    before = fixture["source"].read_bytes()
    result = fixture["run"]()
    assert fixture["source"].read_bytes() == before
    assert result["completed"] == result["verified_completed"] == 0
    assert result["success"] is False


def test_archive_replay_note_failure_before_cleanup_keeps_source(completed_archive, monkeypatch):
    fixture = completed_archive

    def fail_note(*_args, **_kwargs):
        raise OSError("isolated Note write failure")

    monkeypatch.setattr("harness_mem.commands.archive_distill.materialize_session_note", fail_note)
    before = fixture["source"].read_bytes()
    result = fixture["run"]()
    assert fixture["source"].read_bytes() == before
    assert result["success"] is False
    assert result["completed"] == result["verified_completed"] == 0
    assert "isolated Note write failure" in result["outcomes"][0]["reason"]


@pytest.mark.parametrize("protection", ["manual_only", "retain_source", "frozen_selection"])
def test_archive_replay_manual_protection_keeps_source(completed_archive, protection):
    from harness_mem.commands.session_inventory import session_reference
    from harness_mem.storage.manual_batch_store import ManualBatchStore
    from harness_mem.storage.transcript_store import TranscriptStore

    fixture = completed_archive
    ledger = TranscriptStore(fixture["data"])
    try:
        if protection == "manual_only":
            ledger.reserve_manual_distill_job(fixture["job"].id)
        elif protection == "retain_source":
            ledger.retain_distill_source(fixture["job"].id)
        else:
            job = fixture["job"]
            ManualBatchStore(fixture["data"]).create("project", str(fixture["root"]), [
                session_reference(job.client, job.session_id, job.source_id, job.source_revision),
            ])
    finally:
        ledger.close()
    before = fixture["source"].read_bytes()
    result = fixture["run"]()
    assert fixture["source"].read_bytes() == before
    assert result["success"] is True
    assert result["verified_completed"] == 1


@pytest.mark.parametrize("fault", ["native_changed", "ledger_changed", "receipt_mismatch"])
def test_archive_replay_revalidates_source_and_receipt(completed_archive, monkeypatch, fault):
    from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter

    fixture = completed_archive
    original = CodexArchiveAdapter.sync_session

    async def change_after_sync(adapter, *args, **kwargs):
        result = await original(adapter, *args, **kwargs)
        ledger = adapter.backend.transcript_store
        if fault == "native_changed":
            # Host envelope changes leave the permitted conversation unchanged.
            with fixture["source"].open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "turn_context", "payload": {"new": True}}) + "\n")
        elif fault == "ledger_changed":
            source = ledger.get_source(fixture["job"].source_id)
            ledger.save_source(source.model_copy(update={"source_revision": "sha256:" + "0" * 64}))
        else:
            ledger.save_deletion_receipt({
                "id": "unrelated-receipt", "project_name": "project", "reason": "processed_source_cleanup",
                "kind": "processed_source_cleanup", "status": "succeeded",
                "verification": {"passed": True}, "scope": {"job_id_sha256": "wrong-job"},
            })
            job = fixture["job"]
            ledger.record_distill_completion_outcome(
                job.id, disposition=job.completion_disposition, reason_codes=job.completion_reason_codes,
                promotion_summary=job.promotion_summary, source_cleanup_status="retained",
                source_cleanup_receipt_id="unrelated-receipt",
            )
        return result

    monkeypatch.setattr(CodexArchiveAdapter, "sync_session", change_after_sync)
    result = fixture["run"]()
    assert fixture["source"].is_file()
    assert result["success"] is False
    assert result["completed"] == result["verified_completed"] == 0


def test_archive_replay_verified_cleanup_preserves_note_identity(completed_archive):
    fixture = completed_archive
    result = fixture["run"]()
    assert result["success"] is True
    assert not fixture["source"].exists()
    assert result["verified_completed"] == 1
    outcome = result["outcomes"][0]
    note = Path(outcome["note"]["path"]).read_text(encoding="utf-8")
    assert fixture["job"].session_id in note
    assert fixture["job"].id in note
    assert outcome["source_revision"] == fixture["job"].source_revision


def test_archive_deleted_receipt_cannot_verify_another_revision(completed_archive):
    from harness_mem.commands.archive_distill import _verify_archive_distill_run
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    fixture = completed_archive
    result = fixture["run"]()
    assert result["success"] is True
    changed = {**result, "outcomes": [{**result["outcomes"][0], "source_revision": "sha256:another-revision"}]}
    backend = LocalMemoryBackend(fixture["data"])
    asyncio.run(backend.init())
    try:
        verification = asyncio.run(_verify_archive_distill_run(backend, result=changed))
    finally:
        asyncio.run(backend.close())
    assert verification["status"] == "partial"
    assert "source_revision_matches" in verification["outcomes"][0]["failed_checks"]


@pytest.mark.parametrize("changed_envelope", [False, True])
def test_archive_deleted_receipt_reintroduced_live_source_is_revalidated(completed_archive, changed_envelope):
    from harness_mem.commands.archive_distill import _source_revision, _verify_archive_distill_run
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    fixture = completed_archive
    original_bytes = fixture["source"].read_bytes()
    result = fixture["run"]()
    assert result["success"] is True
    assert not fixture["source"].exists()
    restored_bytes = original_bytes
    if changed_envelope:
        restored_bytes += (json.dumps({"type": "turn_context", "payload": {"restored": True}}) + "\n").encode()
    fixture["source"].write_bytes(restored_bytes)
    assert _source_revision(fixture["source"]) == fixture["job"].source_revision
    backend = LocalMemoryBackend(fixture["data"])
    asyncio.run(backend.init())
    try:
        verification = asyncio.run(_verify_archive_distill_run(backend, result=result))
    finally:
        asyncio.run(backend.close())
    assert verification["status"] == "partial"
    checks = verification["outcomes"][0]["checks"]
    assert checks["source_binding_valid"] is False
    assert checks["source_cleanup_verified"] is False
    assert fixture["source"].read_bytes() == restored_bytes


def test_archive_replay_exception_after_cleanup_uses_frozen_revision(completed_archive, monkeypatch):
    from harness_mem.mcp import distill_handlers

    fixture = completed_archive
    original = distill_handlers._cleanup_completed_distill_source

    def cleanup_then_interrupt(*args, **kwargs):
        original(*args, **kwargs)
        assert not fixture["source"].exists()
        raise RuntimeError("interrupted after native cleanup")

    monkeypatch.setattr(distill_handlers, "_cleanup_completed_distill_source", cleanup_then_interrupt)
    result = fixture["run"]()
    assert result["success"] is False
    assert result["completed"] == result["verified_completed"] == 0
    assert result["deferred"] == 1
    assert "interrupted after native cleanup" in result["outcomes"][0]["reason"]
    index = json.loads(Path(result["terminal_index"]).read_text(encoding="utf-8"))
    assert index["attempts"]["completed-replay"]["source_revision"] == fixture["job"].source_revision


@pytest.mark.parametrize("disposition", ["verified_completed", "quarantined"])
def test_archive_revision_change_has_one_current_lifecycle_state(tmp_path, monkeypatch, disposition):
    root = tmp_path / "project"
    root.mkdir()
    _write_archive(tmp_path / "archives", root, "changed-source")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("harness_mem.commands.archive_distill.load_merged_config",
                        lambda *_: MergedConfig(archive_distill_project_scope="current"))
    index = tmp_path / "data" / "archive_distill" / "terminal_index.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"version": 1, "sessions": {"changed-source": {
        "project_name": root.name, "project_root": str(root),
        "source_revision": "sha256:old-revision", "disposition": disposition,
    }}}), encoding="utf-8")
    before = index.read_bytes()
    result = asyncio.run(run_archive_distill_batch(
        control_root=root, apply=False, archive_dir=tmp_path / "archives", data_dir=tmp_path / "data",
    ))
    for counts in (result["terminal"], result["lifecycle_terminal"]):
        assert counts["verified_completed"] == counts["quarantined"] == 0
        assert counts["pending_eligible"] == counts["total"] == 1
        assert counts["conserved"] is True
    assert index.read_bytes() == before
