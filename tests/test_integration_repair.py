from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import harness_mem.commands.integration_cmds as integration_cmds
import harness_mem.integration.repair as repair
from harness_mem.integration.installer import HookInstallResult


def test_repair_keeps_per_stage_results_after_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook_calls: list[str] = []
    command_calls: list[str] = []

    def install_hooks(
        client: str,
        root: Path,
        *,
        force: bool,
        hook_runner: Path | None = None,
    ):
        hook_calls.append(client)
        if client == "cursor":
            raise OSError("hook write failed")
        return [
            HookInstallResult(
                target_path=root / f"{client}-hook",
                status="installed",
            )
        ]

    def sync_commands(*, client: str, **_kwargs):
        command_calls.append(client)
        return SimpleNamespace(
            status="unchanged",
            destination_dir=tmp_path / f"{client}-commands",
        )

    monkeypatch.setattr(repair, "_install_hooks", install_hooks)
    monkeypatch.setattr(repair, "sync_host_commands", sync_commands)

    report = repair.repair_integrations(
        clients=("cursor", "codex"),
        project_root=tmp_path,
    )

    assert report.status == "partial_failure"
    assert report.success is False
    assert hook_calls == ["cursor", "codex"]
    assert command_calls == ["cursor", "codex"]
    assert [
        (result.host, result.stage, result.status) for result in report.results
    ] == [
        ("cursor", "hooks", "failed"),
        ("cursor", "commands", "unchanged"),
        ("codex", "hooks", "installed"),
        ("codex", "commands", "unchanged"),
    ]
    assert report.to_dict()["success"] is False


def test_repair_reports_unsupported_stage_without_dropping_other_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported_hooks(
        client: str,
        root: Path,
        *,
        force: bool,
        hook_runner: Path | None = None,
    ):
        raise NotImplementedError("hook API unavailable")

    monkeypatch.setattr(repair, "_install_hooks", unsupported_hooks)
    monkeypatch.setattr(
        repair,
        "sync_host_commands",
        lambda **_kwargs: SimpleNamespace(
            status="installed",
            destination_dir=tmp_path / "commands",
        ),
    )

    report = repair.repair_integrations(
        clients=("hermes",),
        project_root=tmp_path,
    )

    assert report.status == "success"
    assert report.success is True
    assert [result.status for result in report.results] == [
        "unsupported",
        "installed",
    ]


def test_repair_contains_unexpected_stage_exception_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def broken_hooks(*_args, **_kwargs):
        raise TypeError("unexpected adapter mismatch")

    def sync_commands(*, client: str, **_kwargs):
        calls.append(client)
        return SimpleNamespace(
            status="unchanged",
            destination_dir=tmp_path / f"{client}-commands",
        )

    monkeypatch.setattr(repair, "_install_hooks", broken_hooks)
    monkeypatch.setattr(repair, "sync_host_commands", sync_commands)

    report = repair.repair_integrations(
        clients=("cursor", "codex"),
        project_root=tmp_path,
    )

    assert report.status == "partial_failure"
    assert report.success is False
    assert calls == ["cursor", "codex"]
    assert [result.status for result in report.results] == [
        "failed",
        "unchanged",
        "failed",
        "unchanged",
    ]


def test_hook_sync_cli_emits_structured_report_and_fails_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = repair.IntegrationRepairReport(
        status="partial_failure",
        success=False,
        results=(
            repair.RepairStageResult(
                host="cursor",
                stage="hooks",
                status="failed",
                error="permission denied",
            ),
            repair.RepairStageResult(
                host="cursor",
                stage="commands",
                status="unchanged",
                artifacts=(str(tmp_path / "commands"),),
            ),
        ),
    )
    monkeypatch.setattr(integration_cmds, "repair_integrations", lambda **_kwargs: report)

    exit_code = integration_cmds.cmd_install_hook_suite(
        "cursor", str(tmp_path), False
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "partial_failure"
    assert payload["success"] is False
    assert payload["results"][0] == {
        "artifacts": [],
        "error": "permission denied",
        "host": "cursor",
        "stage": "hooks",
        "status": "failed",
    }
