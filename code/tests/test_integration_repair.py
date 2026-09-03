from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness_mem.commands.integration_cmds as integration_cmds
import harness_mem.integration.repair as repair
from harness_mem.integration.installer import HookInstallResult


def test_project_hook_repair_continues_after_one_host_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def install_hooks(client, root, *, force, hook_runner=None):
        calls.append(client)
        if client == "cursor":
            raise OSError("hook write failed")
        return [
            HookInstallResult(
                target_path=root / f"{client}-hook",
                status="installed",
            )
        ]

    monkeypatch.setattr(repair, "_install_hooks", install_hooks)

    report = repair.repair_project_hooks(
        clients=("cursor", "codex"), project_root=tmp_path
    )

    assert report.status == "partial_failure"
    assert report.success is False
    assert calls == ["cursor", "codex"]
    assert [(result.host, result.status) for result in report.results] == [
        ("cursor", "failed"),
        ("codex", "installed"),
    ]


def test_project_hook_repair_reports_unsupported_host_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repair,
        "_install_hooks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            NotImplementedError("hook API unavailable")
        ),
    )

    report = repair.repair_project_hooks(clients=("hermes",), project_root=tmp_path)

    assert report.status == "unsupported"
    assert report.success is False
    assert report.results[0].status == "unsupported"


def test_hook_sync_cli_emits_only_hook_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = repair.HookRepairReport(
        status="failed",
        success=False,
        results=(
            repair.HookRepairResult(
                host="cursor",
                status="failed",
                error="permission denied",
            ),
        ),
    )
    monkeypatch.setattr(
        integration_cmds, "repair_project_hooks", lambda **_kwargs: report
    )

    exit_code = integration_cmds.cmd_install_hook_suite(
        "cursor", str(tmp_path), False
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["success"] is False
    assert payload["results"] == [
        {
            "artifacts": [],
            "error": "permission denied",
            "host": "cursor",
            "status": "failed",
        }
    ]
