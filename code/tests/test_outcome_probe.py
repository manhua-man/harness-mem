from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from harness_mem.outcome_probe import (
    collect_outcomes,
    inspect_autonomous_outcome,
    inspect_distill_notes,
    inspect_hook_outcome,
    inspect_retrieval_outcome,
)
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.qualification.distill_outcome_probe import (
    run_distill_outcome_probe,
)
from harness_mem.hook_receipts import record_hook_execution
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _job(*, session_id: str, completed_at: datetime, summary: str):
    return SimpleNamespace(
        id=f"job-{session_id}",
        session_id=session_id,
        status="completed",
        completed_at=completed_at,
        semantic_review={"session_summary": summary},
    )


def test_hook_probe_accepts_fresh_interleaved_codex_actions(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    hook_file = project_root / ".codex" / "hooks.json"
    hook_file.parent.mkdir()
    hook_file.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],'
        '"Stop":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "harness_mem.outcome_probe.collect_hook_file_statuses",
        lambda *_args, **_kwargs: [
            SimpleNamespace(exists=True, configured=True)
        ],
    )
    record_hook_execution(
        tmp_path,
        project_root=project_root,
        project_name="demo",
        client="codex",
        action="wake-start",
        trigger_id="session-a",
        source="native-hook",
    )
    record_hook_execution(
        tmp_path,
        project_root=project_root,
        project_name="demo",
        client="codex",
        action="post-turn-maintenance",
        trigger_id="session-b",
        source="native-hook",
    )

    result = inspect_hook_outcome(
        tmp_path,
        project_root=project_root,
        client="codex",
    )

    assert result["actions_verified"] is True
    assert result["session_pair_status"] == "mismatched"
    assert result["lifecycle_verified"] is False


def test_autonomous_probe_accepts_isolated_responses_to_codex_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    provider = {
        "name": "responses_api->codex_exec",
        "schema_valid": True,
        "sandbox": "read-only",
        "ephemeral": True,
        "cwd_isolated": True,
        "hooks_disabled": True,
        "plugins_disabled": True,
        "mcp_disabled": True,
        "rules_ignored": True,
        "config_isolated": True,
    }
    monkeypatch.setattr(
        "harness_mem.outcome_probe.read_autonomous_receipt",
        lambda *_args, **_kwargs: {"last_verified_completion": {"provider": provider}},
    )

    result = inspect_autonomous_outcome(
        tmp_path,
        project_name="demo",
        project_root=project_root,
        jobs=[],
    )

    assert result["provider_isolated"] is True


def test_distill_note_probe_requires_real_meaningful_note(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    jobs = [
        _job(
            session_id="present-session",
            completed_at=now,
            summary="A sufficiently precise summary of the completed session.",
        ),
        _job(
            session_id="missing-session",
            completed_at=now,
            summary="Another sufficiently precise completed-session summary.",
        ),
    ]
    (tmp_path / "present-session.md").write_text(
        "# Session present-session\n\n## Scope\nUseful context.\n\n"
        "## Final outcome\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        jobs,
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["unique_completed_sessions"] == 2
    assert result["notes_meaningful"] == 1
    assert result["note_coverage"] == 0.5
    assert result["note_coverage_complete"] is False
    assert result["semantic_summary_coverage_complete"] is True


def test_distill_note_probe_rejects_long_renderer_placeholder(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    job = _job(
        session_id="placeholder-session",
        completed_at=now,
        summary="The session topic could not be recovered from the available evidence.",
    )
    path = tmp_path / "revisions" / job.id / "placeholder-session.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# placeholder-session\n\n## 会话主题\nRecovered topic.\n\n"
        "## 最终结果\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        [job],
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["semantic_summaries_meaningful"] == 0
    assert result["semantic_summary_coverage_complete"] is False
    assert result["notes"][0]["semantic_summary_present"] is False


def test_distill_note_probe_prefers_latest_job_bound_revision_note(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    old_job = _job(
        session_id="growing-session",
        completed_at=now - timedelta(minutes=5),
        summary="The earlier revision completed a preliminary review.",
    )
    latest_job = _job(
        session_id="growing-session",
        completed_at=now,
        summary="The latest revision completed the final review independently.",
    )
    path = (
        tmp_path
        / "revisions"
        / latest_job.id
        / "growing-session.md"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Session growing-session\n\n## 会话主题\nUseful context.\n\n"
        "## 最终结果\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        [old_job, latest_job],
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["unique_completed_sessions"] == 1
    assert result["note_coverage_complete"] is True
    assert result["notes"][0]["path"] == str(path)


def test_retrieval_probe_requires_current_truth_to_return_from_normal_search(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    data_dir = tmp_path / "data"
    project_root = tmp_path / "demo"
    project_root.mkdir()
    source = project_root / "SOURCE.md"
    source.write_text("# Source\n", encoding="utf-8")
    backend = LocalMemoryBackend(data_dir)
    asyncio.run(backend.init())
    try:
        entry = KnowledgeEntry(
            id="knowledge-1",
            project_name="demo",
            module_path=["Testing"],
            title="Direct runtime evidence",
            statement="Outcome verification must retrieve current knowledge through normal search.",
            verified_at=datetime.now(timezone.utc),
        )
        candidate = KnowledgeCandidate(
            id="retrieval-outcome-seed",
            project_name="demo",
            candidate_type="memory",
            statement="Outcome retrieval fixture.",
        )
        decision = AssimilationDecision(
            id="retrieval-outcome-mutation",
            project_name="demo",
            candidate_id=candidate.id,
            disposition="add",
            canonical_truth_ids=[entry.id],
            reason="Test fixture.",
        )
        source_ref = ProjectKnowledgeSourceRef(
            label="SOURCE.md",
            target=source.resolve().as_uri(),
            kind="repository",
            digest="a" * 64,
        )
        asyncio.run(backend.structured_store.knowledge_store.save_candidate(candidate))
        asyncio.run(
            backend.structured_store.knowledge_store.apply_truth_mutation(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=decision,
                added_entries=[entry],
                predecessor_entries=[],
                source_refs_by_entry={entry.id: [source_ref]},
            )
        )
        asyncio.run(
            backend.structured_store.knowledge_store.cleanup_candidate(candidate.id)
        )
    finally:
        asyncio.run(backend.close())

    result = inspect_retrieval_outcome(data_dir, "demo")

    assert result["readable_truth_count"] == 1
    assert result["probe_attempted"] is True
    assert result["probe_hit"] is True
    assert result["target_title"] == "Direct runtime evidence"

    command = [
        sys.executable,
        "-m",
        "harness_mem.outcome_probe",
        "--project",
        "demo",
        "--project-root",
        str(project_root),
        "--data-dir",
        str(data_dir),
        "--section",
        "retrieval",
        "--compact",
    ]
    completed = subprocess.run(
        command,
        cwd=Path.cwd(),
        env={**os.environ, "HARNESS_MEM_DISABLE_EMBEDDINGS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["retrieval"]["probe_hit"] is True


def test_partial_distill_runtime_outcome_probe() -> None:
    result = run_distill_outcome_probe()

    assert result["verified"] is True
    assert result["partial_candidate_promoted"] is True
    assert result["handoff_job_bound"] is True
    assert result["dream_blocked_for_partial"] is True
    assert result["note_paths_distinct"] is True


def test_collect_outcomes_can_select_one_section_without_running_others(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    job = _job(
        session_id="selected-session",
        completed_at=datetime.now(timezone.utc),
        summary="A useful summary for the selected autonomous outcome.",
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe._read_distill_jobs",
        lambda *_args: calls.append("jobs") or [job],
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_autonomous_outcome",
        lambda *_args, **_kwargs: calls.append("autonomous") or {"state": "idle"},
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_hook_outcome",
        lambda *_args, **_kwargs: calls.append("hooks") or {},
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_dream_outcome",
        lambda *_args, **_kwargs: calls.append("dream") or {},
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_distill_notes",
        lambda *_args, **_kwargs: calls.append("distill") or {},
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_retrieval_outcome",
        lambda *_args, **_kwargs: calls.append("retrieval") or {},
    )

    result = collect_outcomes(
        project_name="demo",
        project_root=tmp_path,
        client="codex",
        data_dir=tmp_path,
        notes_dir=tmp_path,
        recent_days=7,
        sections=["autonomous"],
    )

    assert result["autonomous"] == {"state": "idle"}
    assert set(result) == {
        "schema_version",
        "project",
        "project_root",
        "observed_at",
        "window_days",
        "autonomous",
    }
    assert calls == ["jobs", "autonomous"]


def test_collect_outcomes_compact_omits_verbose_detail_arrays(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness_mem.outcome_probe._read_distill_jobs", lambda *_: [])
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_distill_notes",
        lambda *_args, **_kwargs: {"note_coverage_complete": True, "notes": [{"id": 1}]},
    )
    monkeypatch.setattr(
        "harness_mem.outcome_probe.inspect_retrieval_outcome",
        lambda *_args, **_kwargs: {"probe_hit": True, "attempts": [{"query": "x"}]},
    )

    result = collect_outcomes(
        project_name="demo",
        project_root=tmp_path,
        client="codex",
        data_dir=tmp_path,
        notes_dir=tmp_path,
        recent_days=7,
        sections=["distill", "retrieval"],
        compact=True,
    )

    assert result["distill"] == {"note_coverage_complete": True}
    assert result["retrieval"] == {"probe_hit": True}
