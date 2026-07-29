from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import (
    cmd_config_get,
    cmd_config_list,
    cmd_config_set,
)
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.config.writer import set_value


def _redirect_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def test_delete_source_after_complete_defaults_to_false(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    config = load_merged_config(project)

    assert MergedConfig().distill_delete_source_after_complete is False
    assert config.distill_delete_source_after_complete is False
    assert config.to_reflection_config()["distill"]["delete_source_after_complete"] is False


def test_user_delete_source_setting_is_overridden_by_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)

    set_value(
        scope="user",
        project_root=project,
        key_path="distill.delete_source_after_complete",
        value="true",
    )
    assert load_merged_config(project).distill_delete_source_after_complete is True

    set_value(
        scope="project",
        project_root=project,
        key_path="distill.delete_source_after_complete",
        value="false",
    )
    assert load_merged_config(project).distill_delete_source_after_complete is False


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("autopilot.enabled", "false", False),
        ("capture.enabled", "false", False),
        ("capture.ignore_clients", '["codex", "cursor", "codex"]', ["codex", "cursor"]),
        ("distill.auto.daily_job_budget", "12", 12),
        ("distill.delete_source_after_complete", "true", True),
        ("dream.auto.trigger", "idle", "idle"),
        ("cost_budget.wake_tokens", "1500", 1500),
    ],
)
def test_config_writer_preserves_typed_values(
    tmp_path: Path,
    key: str,
    value: str,
    expected: object,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    path = set_value(
        scope="project",
        project_root=project,
        key_path=key,
        value=value,
    )
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    current: object = payload
    for part in key.split("."):
        assert isinstance(current, dict)
        current = current[part]
    assert current == expected
    load_merged_config(project)


def test_config_set_rejects_invalid_delete_source_boolean(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    exit_code = cmd_config_set(
        "distill.delete_source_after_complete",
        "sometimes",
        "project",
        str(project),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "allowed: {true, false}" in captured.err
    assert not (project / ".harness-mem.toml").exists()


def test_enabling_delete_source_requires_one_persistent_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)

    assert (
        cmd_config_set(
            "distill.delete_source_after_complete",
            "true",
            "user",
            str(project),
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "rerun with --confirm" in captured.err
    assert not (home / ".harness-mem" / "config.toml").exists()

    assert (
        cmd_config_set(
            "distill.delete_source_after_complete",
            "true",
            "user",
            str(project),
            confirm=True,
        )
        == 0
    )
    assert load_merged_config(project).distill_delete_source_after_complete is True
    capsys.readouterr()

    # Re-applying an already enabled value is not a new destructive transition.
    assert (
        cmd_config_set(
            "distill.delete_source_after_complete",
            "true",
            "user",
            str(project),
        )
        == 0
    )


def test_disabling_delete_source_never_requires_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    set_value(
        scope="user",
        project_root=project,
        key_path="distill.delete_source_after_complete",
        value="true",
    )

    assert (
        cmd_config_set(
            "distill.delete_source_after_complete",
            "false",
            "user",
            str(project),
        )
        == 0
    )
    assert load_merged_config(project).distill_delete_source_after_complete is False


def test_config_get_and_list_include_all_typed_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    set_value(
        scope="user",
        project_root=project,
        key_path="distill.delete_source_after_complete",
        value="true",
    )

    assert cmd_config_get("distill.delete_source_after_complete", str(project)) == 0
    assert capsys.readouterr().out == "true\n"

    assert cmd_config_list(str(project)) == 0
    output = capsys.readouterr().out
    assert "autopilot.enabled = true  (default)" in output
    assert "capture.enabled = true  (default)" in output
    assert "distill.auto.enabled = true  (default)" in output
    assert "distill.delete_source_after_complete = true  (user)" in output
    assert "dream.auto.enabled = true  (default)" in output
    assert "cost_budget.wake_tokens = 2000  (default)" in output
