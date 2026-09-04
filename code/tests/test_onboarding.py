from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import harness_mem.commands.onboarding as onboarding


def test_quickstart_installs_one_global_entry_without_touching_project(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: "codex")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(status="installed"),
    )

    result = onboarding.cmd_quickstart(client="auto")

    assert result == 0
    assert calls == [{"client": "codex"}]
    assert not (workspace / ".harness-mem.toml").exists()
    assert not (workspace / ".codex").exists()
    output = capsys.readouterr().out
    assert "Installed $hm for codex" in output
    assert "Start a new Agent task to use it" in output
    assert "project" not in output.lower()
    assert "Hooks" not in output
    assert "MCP" not in output


def test_quickstart_uses_explicit_host_without_inspecting_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda *, client: calls.append(client) or SimpleNamespace(status="installed"),
    )

    monkeypatch.chdir(first)
    assert onboarding.cmd_quickstart(client="cursor") == 0
    monkeypatch.chdir(second)
    assert onboarding.cmd_quickstart(client="cursor") == 0

    assert calls == ["cursor", "cursor"]
    assert list(first.iterdir()) == []
    assert list(second.iterdir()) == []


def test_quickstart_auto_stops_when_current_app_is_unknown(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: None)
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown host must not install another app's files")
        ),
    )

    assert onboarding.cmd_quickstart(client="auto") == 1
    output = capsys.readouterr().out
    assert "Could not detect the current app" in output
    assert "harness-mem quickstart --client cursor" in output


def test_quickstart_does_not_claim_success_when_entry_install_fails(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("permission denied")),
    )

    assert onboarding.cmd_quickstart(client="cursor") == 1
    output = capsys.readouterr().out
    assert "Could not install the memory entry" in output
    assert "Installed /hm" not in output
