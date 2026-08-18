from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import (
    cmd_config_get,
    cmd_config_list,
    cmd_config_set,
)
from harness_mem.commands import support
from harness_mem.config.errors import ConfigValidationError
from harness_mem.config.merge import (
    PUBLIC_CONFIG_KEY_PATHS,
    MergedConfig,
    load_merged_config,
)
from harness_mem.config.writer import set_value


def _redirect_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def test_automation_and_delete_source_defaults_are_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_home(monkeypatch, tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    config = load_merged_config(project)

    assert MergedConfig().capture_enabled is True
    assert config.capture_enabled is True
    assert MergedConfig().capture_private_tags is True
    assert config.capture_private_tags is True
    assert MergedConfig().distill_auto_enabled is True
    assert config.distill_auto_enabled is True
    assert MergedConfig().distill_delete_source_after_complete is True
    assert config.distill_delete_source_after_complete is True
    assert MergedConfig().distill_autonomous_enabled is False
    assert config.distill_autonomous_enabled is False
    assert config.to_reflection_config()["distill"]["delete_source_after_complete"] is True


def test_archive_distill_defaults_are_public_and_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_home(monkeypatch, tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    config = load_merged_config(project)

    assert config.archive_distill_enabled is False
    assert config.archive_distill_batch_size == 3
    assert config.archive_distill_daily_limit == 20
    assert config.archive_distill_order == "recent_first"
    assert config.archive_distill_project_scope == "current"
    assert config.archive_distill_unresolved_project == "defer"
    assert config.archive_distill_warn_tokens == 15000
    assert config.archive_distill_warn_seconds == 40
    assert config.archive_distill_require_answer_packet is True
    assert config.archive_distill_report_promotions is True
    assert {
        "archive_distill.enabled",
        "archive_distill.batch_size",
        "archive_distill.daily_limit",
        "archive_distill.order",
        "archive_distill.project_scope",
        "archive_distill.unresolved_project",
        "archive_distill.warn_tokens",
        "archive_distill.warn_seconds",
        "archive_distill.require_answer_packet",
        "archive_distill.report_promotions",
    } <= set(PUBLIC_CONFIG_KEY_PATHS)


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
        ("capture.enabled", "false", False),
        ("capture.ignore_clients", '["codex", "cursor", "codex"]', ["codex", "cursor"]),
        ("distill.auto.enabled", "false", False),
        ("distill.autonomous.enabled", "false", False),
        ("distill.delete_source_after_complete", "true", True),
        ("archive_distill.enabled", "true", True),
        ("archive_distill.batch_size", "5", 5),
        ("archive_distill.daily_limit", "30", 30),
        ("archive_distill.order", "oldest_first", "oldest_first"),
        ("archive_distill.project_scope", "current", "current"),
        ("archive_distill.unresolved_project", "skip", "skip"),
        ("archive_distill.warn_tokens", "12000", 12000),
        ("archive_distill.warn_seconds", "45", 45),
        ("archive_distill.require_answer_packet", "false", False),
        ("archive_distill.report_promotions", "false", False),
        ("dream.auto.enabled", "false", False),
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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("distill.auto.daily_job_budget", "12"),
        ("dream.auto.trigger", "idle"),
        ("dream.handle.auto_apply", "false"),
        ("cost_budget.wake_tokens", "1500"),
    ],
)
def test_config_set_rejects_internal_runtime_tuning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    key: str,
    value: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert cmd_config_set(key, value, "project", str(project)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "internal compatibility key" in captured.err
    assert not (project / ".harness-mem.toml").exists()


def test_config_set_rejects_unknown_public_policy_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert cmd_config_set("mystery.option", "true", "project", str(project)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "mystery.option" in captured.err
    assert not (project / ".harness-mem.toml").exists()


def test_removed_autopilot_key_is_ignored_by_loader_and_absent_from_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _redirect_home(monkeypatch, tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".harness-mem.toml").write_text(
        "[autopilot]\nenabled = false\n",
        encoding="utf-8",
    )

    config = load_merged_config(project)
    assert "autopilot" not in config.to_reflection_config()
    assert "autopilot.enabled" not in PUBLIC_CONFIG_KEY_PATHS
    assert cmd_config_get("autopilot.enabled", str(project)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "key not found" in captured.err
    assert cmd_config_set("autopilot.enabled", "true", "project", str(project)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid value" in captured.err
    assert cmd_config_list(str(project)) == 0
    assert "autopilot.enabled" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("archive_distill.batch_size", "0"),
        ("archive_distill.batch_size", "101"),
        ("archive_distill.daily_limit", "0"),
        ("archive_distill.daily_limit", "10001"),
        ("archive_distill.order", "random"),
        ("archive_distill.project_scope", "mystery"),
        ("archive_distill.unresolved_project", "guess"),
        ("archive_distill.warn_tokens", "0"),
        ("archive_distill.warn_seconds", "0"),
    ],
)
def test_archive_distill_rejects_values_outside_public_contract(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ConfigValidationError):
        set_value(
            scope="project",
            project_root=project,
            key_path=key,
            value=value,
        )


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


def test_enabling_autonomous_distill_requires_persistent_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)

    assert cmd_config_set(
        "distill.autonomous.enabled", "true", "project", str(project)
    ) == 1
    captured = capsys.readouterr()
    assert "model quota" in captured.err
    assert "--confirm" in captured.err

    assert (
        cmd_config_set(
            "distill.autonomous.enabled",
            "true",
            "project",
            str(project),
            confirm=True,
        )
        == 0
    )
    assert load_merged_config(project).distill_autonomous_enabled is True


def test_user_autonomous_authorization_is_ignored_and_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    user_config = home / ".harness-mem" / "config.toml"
    user_config.parent.mkdir()
    user_config.write_text(
        "[distill.autonomous]\nenabled = true\n",
        encoding="utf-8",
    )

    assert load_merged_config(project).distill_autonomous_enabled is False
    assert cmd_config_list(str(project)) == 0
    listed = capsys.readouterr().out
    assert "distill.autonomous.enabled = false  (default)" in listed
    assert cmd_config_set(
        "distill.autonomous.enabled", "true", "user", str(project), confirm=True
    ) == 1
    assert "project scope" in capsys.readouterr().err


def test_config_get_and_list_include_only_public_policy_keys(
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
    assert "autopilot.enabled" not in output
    assert "capture.enabled = true  (default)" in output
    assert "distill.auto.enabled = true  (default)" in output
    assert "distill.delete_source_after_complete = true  (user)" in output
    assert "archive_distill.enabled = false  (default)" in output
    assert "archive_distill.batch_size = 3  (default)" in output
    assert "archive_distill.daily_limit = 20  (default)" in output
    assert "archive_distill.order = recent_first  (default)" in output
    assert "archive_distill.project_scope = current  (default)" in output
    assert "archive_distill.unresolved_project = defer  (default)" in output
    assert "archive_distill.warn_tokens = 15000  (default)" in output
    assert "archive_distill.warn_seconds = 40  (default)" in output
    assert "archive_distill.require_answer_packet = true  (default)" in output
    assert "archive_distill.report_promotions = true  (default)" in output
    assert "dream.auto.enabled = true  (default)" in output
    assert "cost_budget.wake_tokens" not in output
    assert "dream.handle.auto_apply" not in output
    listed = {
        line.split(" =", 1)[0]
        for line in output.splitlines()
        if " = " in line
    }
    assert listed == set(PUBLIC_CONFIG_KEY_PATHS)


def test_config_list_runtime_detail_adds_read_only_tuning_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    config_dir = home / ".harness-mem"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[cost_budget]\ndistill_tokens = 4500\n",
        encoding="utf-8",
    )

    assert cmd_config_list(str(project), detail="runtime") == 0
    output = capsys.readouterr().out
    assert "runtime tuning (read-only):" in output
    assert "distill.auto.max_jobs_per_wake = 2  (default)" in output
    assert "distill.auto.target_backlog = 2  (default)" in output
    assert "distill.auto.daily_job_budget = 8  (default)" in output
    assert "cost_budget.distill_tokens = 4500  (user)" in output
    assert "dream.auto.min_interval_hours = 24  (default)" in output
    assert "dream.auto.idle_seconds = 900  (default)" in output
    assert "dream.auto.max_runtime_seconds = 120  (default)" in output


def test_legacy_json_toml_and_project_config_share_one_merge_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    config_dir = home / ".harness-mem"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "capture": {"enabled": False},
                "wake": {"auto_ingest": False},
                "embedding": {"model_id": "legacy-model"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "config.toml").write_text(
        "[capture]\nenabled = true\n[dream.auto]\nenabled = false\n",
        encoding="utf-8",
    )
    (project / ".harness-mem.toml").write_text(
        "[capture]\nenabled = false\n",
        encoding="utf-8",
    )

    merged = load_merged_config(project)
    runtime = merged.to_reflection_config()
    assert merged.capture_enabled is False
    assert merged.dream_auto_enabled is False
    assert runtime["wake"]["auto_ingest"] is False
    assert runtime["embedding"]["model_id"] == "legacy-model"

    monkeypatch.chdir(project)
    assert support.get_config() == runtime
