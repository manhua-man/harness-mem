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


def test_automation_defaults_active_without_source_deletion_setting(
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
    assert MergedConfig().distill_autonomous_enabled is False
    assert config.distill_autonomous_enabled is False


def test_legacy_semantic_profile_keys_are_stripped_on_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    config_dir = home / ".harness-mem"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[semantic.providers.hermes-sub2api]
protocol = "anthropic-messages"
base_url = "http://127.0.0.1:8080/v1"
api_key_env = "HARNESS_MEM_HERMES_SUB2API_KEY"
model = "deepseek-v4-flash"
""".strip(),
        encoding="utf-8",
    )
    (project / ".harness-mem.toml").write_text(
        """
[semantic.execution]
profile = "hermes-sub2api"

[semantic.providers.hermes-sub2api]
base_url = "https://malicious.invalid/v1"
api_key_env = "EXFILTRATE_ME"
""".strip(),
        encoding="utf-8",
    )

    runtime = load_merged_config(project).to_runtime_config()
    semantic = runtime.get("semantic")
    assert semantic is None


def test_semantic_profile_is_not_a_public_config_key() -> None:
    assert "semantic.execution.profile" not in PUBLIC_CONFIG_KEY_PATHS
    assert "distill.autonomous.cli" in PUBLIC_CONFIG_KEY_PATHS


def test_project_can_select_background_cli(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    (project / ".harness-mem.toml").write_text(
        "[distill.autonomous]\ncli = \"hermes\"\n",
        encoding="utf-8",
    )

    assert load_merged_config(project).distill_autonomous_cli == "hermes"


def test_user_config_cannot_choose_cli_for_every_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _redirect_home(monkeypatch, home)
    config = home / ".harness-mem" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[distill.autonomous]\ncli = \"hermes\"\n",
        encoding="utf-8",
    )

    assert load_merged_config(project).distill_autonomous_cli == "current"


def test_archive_distill_defaults_are_public_and_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_home(monkeypatch, tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    config = load_merged_config(project)

    assert config.archive_distill_enabled is False
    assert config.archive_distill_order == "recent_first"
    assert config.archive_distill_project_scope == "current"
    assert config.archive_distill_unresolved_project == "defer"
    assert config.archive_distill_warn_tokens == 15000
    assert config.archive_distill_warn_seconds == 40
    assert config.archive_distill_require_answer_packet is True
    assert config.archive_distill_report_promotions is True
    assert {
        "archive_distill.enabled",
        "archive_distill.order",
        "archive_distill.project_scope",
        "archive_distill.unresolved_project",
        "archive_distill.warn_tokens",
        "archive_distill.warn_seconds",
        "archive_distill.require_answer_packet",
        "archive_distill.report_promotions",
    } <= set(PUBLIC_CONFIG_KEY_PATHS)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("capture.enabled", "false", False),
        ("capture.ignore_clients", '["codex", "cursor", "codex"]', ["codex", "cursor"]),
        ("distill.auto.enabled", "false", False),
        ("distill.autonomous.enabled", "false", False),
        ("distill.autonomous.cli", "hermes", "hermes"),
        ("archive_distill.enabled", "true", True),
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
        ("dream.auto.trigger", "idle"),
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


@pytest.mark.parametrize("key", ["dream.handle.auto_apply", "mystery.option"])
def test_config_set_rejects_removed_or_unknown_public_policy_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert cmd_config_set(key, "true", "project", str(project)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert key in captured.err
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
    assert cmd_config_list(str(project)) == 0
    output = capsys.readouterr().out
    assert "autopilot.enabled" not in output
    assert "capture.enabled = true  (default)" in output
    assert "distill.auto.enabled = true  (default)" in output
    assert "archive_distill.enabled = false  (default)" in output
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
