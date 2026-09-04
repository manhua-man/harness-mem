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


def _write_config(root: Path, *, enabled: bool, require_answer_packet: bool = True) -> None:
    root.joinpath(".harness-mem.toml").write_text(
        "[archive_distill]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        "batch_size = 3\n"
        "daily_limit = 20\n"
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
            daily_limit=4,
        )
    )

    assert result["policy"]["batch_size"] == 4
    assert result["policy"]["daily_limit"] == 4
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


def test_archive_sanitized_retrieval_includes_provisional_relations(
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
                allow_sanitized_project_retrieval=True,
            )
        )
    finally:
        asyncio.run(backend.close())

    assert result["status"] == "passed"
    assert result["items"][0]["retrieval_mode"] == "legacy_project_truth"


def test_archive_repair_only_reverifies_deleted_partial_receipt_without_provider(
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
    assert entry["repaired_from_partial_receipt"] is True
    assert entry["repair_kind"] == "completed_job_after_deferred_receipt"


def test_archive_attempt_budget_is_durable_across_utc_days(
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
    assert second["quarantined"] == 1
    assert third["selected"] == []
    assert third["terminal"]["quarantined"] == 1
    assert calls == 2
    index = json.loads(Path(second["terminal_index"]).read_text(encoding="utf-8"))
    assert index["attempts"]["session-bounded-retry"]["count"] == 2
    assert index["sessions"]["session-bounded-retry"]["disposition"] == "quarantined"


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
