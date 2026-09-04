from __future__ import annotations

import asyncio
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.authorization import BackgroundStatus
from harness_mem.core.schemas.observation import Observation
from harness_mem.integration_health import (
    _build_autonomous_health_card,
    build_integration_health,
)
from harness_mem.hook_receipts import record_hook_execution
from harness_mem.host_entry.__main__ import _adapter_request
from harness_mem.integration.repair import _suite_specs
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _auth(**overrides: object) -> BackgroundStatus:
    base = {
        "ready": True,
        "on": True,
        "reason": "ok",
        "selected_cli": "codex",
    }
    base.update(overrides)
    return BackgroundStatus(**base)


def test_integration_health_summarizes_current_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    hook_dir = workspace / ".cursor" / "hooks"
    hook_dir.mkdir(parents=True)
    (hook_dir / "session-start.sh").write_text(
        "harness-mem-hook wake", encoding="utf-8"
    )
    (hook_dir / "after-agent.sh").write_text(
        "harness-mem-hook maintain",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "cursor")

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await persist_session_snapshot(
                backend,
                Observation(
                    session_id="cursor-session",
                    client="cursor",
                    raw_content="User: inspect integration health",
                    content_type="transcript",
                    metadata={"project_name": "project"},
                ),
                project_name="project",
                project_root=str(workspace),
                client="cursor",
                session_id="cursor-session",
                source_kind="jsonl",
                source_uri="file:///cursor-session.jsonl",
                source_text="User: inspect integration health\n",
            )
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())

    assert health["project"]["status"] == "ok"
    assert health["host"]["client"] == "cursor"
    assert health["hooks"]["status"] == "ok"
    assert health["transcript"]["status"] == "synced"
    assert health["transcript"]["session_count"] == 1
    assert health["transcript"]["latest_source_coverage"] == "complete"
    distill = health["pending_distill"]
    assert distill["status"] == "waiting_for_agent"
    assert distill["queued"] == 1
    assert distill["processing"] == 0
    assert distill["parked"] == 0
    assert distill["completed_chunks"] == 0
    assert distill["expected_chunks"] == 1
    assert distill["legacy_audit_only"] == 0
    assert distill["agent_required"] is True
    assert distill["background_semantic_processing"] is False
    assert distill["pending_total"] == 1
    assert distill["drain_estimate"]["status"] == "unavailable"
    assert distill["stuck_reasons"][0]["code"] == "zero_7d_throughput"
    assert health["summary"].startswith("project=ok | host=cursor | hooks=ok (2/2)")
    assert health["health_card"]["status"] == "disabled"
    assert health["health_card"]["alert"] is False


def test_health_card_is_idle_safe_and_ignores_cold_parked_backlog() -> None:
    card = _build_autonomous_health_card(
        authorization=_auth(),
        autonomous={
            "receipt_exists": True,
            "lifecycle_verified": True,
            "state": "succeeded",
            "last_semantic_success_at": "2026-08-11T16:25:41+00:00",
            "trigger_id": "session-1",
            "job_id": "job-1",
            "provider": {
                "total_tokens": 6001,
                "duration_seconds": 13.48,
                "model": "gpt-test",
            },
            "note": {"path": "C:/notes/session-1.md"},
        },
        jobs=[],
        drainer={
            "active": 1,
            "parked": 199,
            "retry_backoff": 0,
            "recovery_exhausted": 0,
            "oldest_stalled_age_hours": 0.0,
        },
        hooks_configured=True,
        post_turn_last_success_at="2026-08-11T16:25:42+00:00",
        now=datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc),
    )
    assert card["authorization"]["selected_cli"] == "codex"

    assert card["status"] == "healthy"
    assert card["alert"] is False
    assert card["chain_verified"] is True
    assert card["queue"] == {
        "active": 1,
        "parked": 199,
        "retry_backoff": 0,
        "overdue": 0,
    }
    assert card["failures_24h"] == 0


def test_health_card_preserves_success_but_reports_latest_deferred_attempt() -> None:
    card = _build_autonomous_health_card(
        authorization=_auth(),
        autonomous={
            "receipt_exists": True,
            "lifecycle_verified": True,
            "state": "deferred",
            "last_semantic_success_at": "2026-08-11T16:25:41+00:00",
            "provider": {"total_tokens": 1000, "duration_seconds": 10.0},
        },
        jobs=[],
        drainer={
            "active": 0,
            "parked": 0,
            "retry_backoff": 0,
            "recovery_exhausted": 0,
            "oldest_stalled_age_hours": 0.0,
        },
        hooks_configured=True,
        post_turn_last_success_at="2026-08-11T16:30:00+00:00",
        now=datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc),
    )

    assert card["chain_verified"] is True
    assert card["status"] == "attention"
    assert card["issue_codes"] == ["latest_batch_failed"]


def test_health_card_alerts_on_performance_and_queue_regressions() -> None:
    card = _build_autonomous_health_card(
        authorization=_auth(),
        autonomous={
            "receipt_exists": True,
            "lifecycle_verified": True,
            "state": "succeeded",
            "provider": {
                "total_tokens": 15_001,
                "duration_seconds": 60.01,
            },
        },
        jobs=[],
        drainer={
            "active": 1,
            "parked": 0,
            "retry_backoff": 1,
            "recovery_exhausted": 0,
            "oldest_stalled_age_hours": 3.0,
        },
        hooks_configured=True,
        post_turn_last_success_at="2026-08-11T16:25:42+00:00",
        now=datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc),
    )

    assert card["status"] == "attention"
    assert card["alert"] is True
    assert card["queue"]["overdue"] == 2
    assert card["issue_codes"] == [
        "queue_overdue",
        "token_regression",
        "latency_regression",
    ]


def test_health_card_alerts_when_recent_hooks_make_no_semantic_progress() -> None:
    card = _build_autonomous_health_card(
        authorization=_auth(),
        autonomous={
            "receipt_exists": True,
            "lifecycle_verified": True,
            "state": "succeeded",
            "last_semantic_success_at": "2026-08-10T08:00:00+00:00",
            "provider": {"total_tokens": 1000, "duration_seconds": 10.0},
        },
        jobs=[],
        drainer={
            "state": "waiting_for_agent",
            "active": 1,
            "parked": 0,
            "retry_backoff": 0,
            "recovery_exhausted": 0,
            "oldest_stalled_age_hours": 0.0,
            "daily_budget_remaining": 1,
        },
        hooks_configured=True,
        post_turn_last_success_at="2026-08-11T11:30:00+00:00",
        now=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
    )

    assert card["status"] == "attention"
    assert card["alert"] is True
    assert card["last_run"]["freshness"] == "stale"
    assert card["issue_codes"] == ["semantic_success_stale"]


def test_integration_health_does_not_guess_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=tmp_path,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())
    assert health["host"] == {"status": "unknown", "client": "unknown"}
    assert health["hooks"]["status"] == "unknown"
    assert health["transcript"]["status"] == "unknown"


def test_codex_health_requires_fresh_execution_proof_for_both_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    hook_path = workspace / ".codex" / "hooks.json"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],"Stop":[]}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")

    async def run() -> tuple[dict, dict, dict, dict]:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            before = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            record_hook_execution(
                backend.data_dir,
                project_root=workspace,
                project_name="project",
                client="codex",
                action="wake-start",
                source="ide_hook",
                trigger_id="session-1",
            )
            after = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            record_hook_execution(
                backend.data_dir,
                project_root=workspace,
                project_name="project",
                client="codex",
                action="post-turn-maintenance",
                source="ide_hook",
                trigger_id="session-2",
            )
            mismatched = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            record_hook_execution(
                backend.data_dir,
                project_root=workspace,
                project_name="project",
                client="codex",
                action="post-turn-maintenance",
                source="ide_hook",
                trigger_id="session-1",
            )
            complete = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            return before, after, mismatched, complete
        finally:
            await backend.close()

    before, after, mismatched, complete = asyncio.run(run())

    assert before["hooks"]["status"] == "review_required"
    assert before["hooks"]["wake_verified"] is False
    assert before["hooks"]["freshness"] == "never"
    assert before["hooks"]["last_success_at"] is None
    assert before["hooks"]["actions"]["wake_start"]["freshness"] == "never"
    assert "Settings > Hooks" in before["hooks"]["action_required"]
    assert after["hooks"]["status"] == "degraded"
    assert after["hooks"]["wake_verified"] is True
    assert after["hooks"]["maintenance_verified"] is False
    assert after["hooks"]["freshness"] == "stale"
    assert after["hooks"]["last_success_at"] is not None
    assert after["hooks"]["action_required"] is not None
    assert after["hooks"]["session_pair_status"] == "incomplete"
    assert mismatched["hooks"]["status"] == "degraded"
    assert mismatched["hooks"]["freshness"] == "fresh"
    assert mismatched["hooks"]["session_pair_status"] == "mismatched"
    assert mismatched["hooks"]["lifecycle_verified"] is False
    assert complete["hooks"]["status"] == "ok"
    assert complete["hooks"]["wake_verified"] is True
    assert complete["hooks"]["maintenance_verified"] is True
    assert complete["hooks"]["freshness"] == "fresh"
    assert complete["hooks"]["session_pair_status"] == "matched"
    assert complete["hooks"]["lifecycle_verified"] is True
    assert complete["hooks"]["actions"]["wake_start"]["trigger_id"] == "session-1"
    assert (
        complete["hooks"]["actions"]["post_turn_maintenance"]["trigger_id"]
        == "session-1"
    )
    assert complete["hooks"]["action_required"] is None


def test_codex_adapters_bind_both_lifecycle_actions_to_session_id(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    args = argparse.Namespace(adapter="codex-start", project_root=str(workspace))
    payload = {"session_id": "thread-1", "turn_id": "turn-1", "cwd": str(workspace)}

    start = _adapter_request(args, payload)
    args.adapter = "codex-stop"
    stop = _adapter_request(args, payload)

    assert start.action == "wake-start"
    assert stop.action == "post-turn-maintenance"
    assert start.trigger_id == stop.trigger_id == "thread-1"

    specs = _suite_specs("codex", workspace, tmp_path / "harness-mem-hook")
    wake_command = json.loads(specs[0].template_vars["WAKE_COMMAND_JSON"])
    assert "--adapter codex-start" in wake_command
    assert "--trigger-id codex-session-start" not in wake_command


def test_codex_health_marks_old_execution_receipts_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    hook_path = workspace / ".codex" / "hooks.json"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],"Stop":[]}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            old_completed_at = (
                datetime.now(timezone.utc) - timedelta(days=2)
            ).isoformat()
            for action in ("wake-start", "post-turn-maintenance"):
                receipt_path = record_hook_execution(
                    backend.data_dir,
                    project_root=workspace,
                    project_name="project",
                    client="codex",
                    action=action,
                    source="ide_hook",
                    trigger_id=f"old-{action}",
                )
                assert receipt_path is not None
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
                payload["completed_at"] = old_completed_at
                receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())

    assert health["hooks"]["status"] == "degraded"
    assert health["hooks"]["freshness"] == "stale"
    assert health["hooks"]["wake_verified"] is False
    assert health["hooks"]["maintenance_verified"] is False
    assert health["hooks"]["actions"]["wake_start"]["age_seconds"] >= 172800
    assert health["hooks"]["actions"]["post_turn_maintenance"]["freshness"] == "stale"


def test_codex_health_marks_changed_hook_configuration_invalid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    hook_path = workspace / ".codex" / "hooks.json"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            record_hook_execution(
                backend.data_dir,
                project_root=workspace,
                project_name="project",
                client="codex",
                action="wake-start",
                source="ide_hook",
                trigger_id="before-change",
            )
            hook_path.write_text(
                '{"hooks":{"SessionStart":[{"command":"harness-mem-hook --changed"}]}}\n',
                encoding="utf-8",
            )
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())

    assert health["hooks"]["status"] == "invalid"
    wake = health["hooks"]["actions"]["wake_start"]
    assert wake["receipt_status"] == "config_mismatch"
    assert wake["config_match"] is False
    assert wake["freshness"] == "never"
    assert wake["last_success_at"] is not None


def test_health_card_disabled_when_background_off(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "cursor")
    monkeypatch.setattr(
        "harness_mem.integration_health.load_merged_config",
        lambda *_args, **_kwargs: __import__(
            "harness_mem.config.merge", fromlist=["MergedConfig"]
        ).MergedConfig(
            distill_autonomous_enabled=False,
        ),
    )

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())

    assert health["health_card"]["status"] == "disabled"
