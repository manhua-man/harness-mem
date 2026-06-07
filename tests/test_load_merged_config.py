"""Tests for ``load_merged_config`` (v2.4.1 Task 2, Req 3.1-3.10).

HOME isolation
--------------
``load_merged_config`` resolves the user-level config path via
``harness_mem.config.merge._user_config_path``, which reads ``Path.home()``.
Tests redirect that lookup to a tmp directory by monkeypatching ``Path.home``
so no test ever reads the real ``~/.harness-mem/config.toml``. A ``project``
directory under ``tmp_path`` stands in for the absolute project root.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from harness_mem.config.errors import (
    ConfigParseError,
    ConfigPathError,
    ConfigValidationError,
)
from harness_mem.config.merge import (
    MergedConfig,
    deep_merge,
    load_merged_config,
)


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` to an isolated tmp dir for user-config lookup."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An existing absolute project directory under tmp_path."""
    proj = tmp_path / "project"
    proj.mkdir()
    return proj


def _write_user_config(home: Path, body: str) -> Path:
    cfg_dir = home / ".harness-mem"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _write_project_config(project: Path, body: str) -> Path:
    path = project / ".harness-mem.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---- Req 3.1 / 3.2: project_root validation ------------------------------


def test_non_absolute_project_root_raises_path_error(home_dir: Path) -> None:
    with pytest.raises(ConfigPathError) as excinfo:
        load_merged_config("relative/path")
    assert excinfo.value.project_root == "relative/path"


def test_nonexistent_dir_raises_path_error(home_dir: Path, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ConfigPathError):
        load_merged_config(str(missing))


def test_file_as_project_root_raises_path_error(
    home_dir: Path, tmp_path: Path
) -> None:
    afile = tmp_path / "afile.txt"
    afile.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigPathError):
        load_merged_config(str(afile))


# ---- Req 3.3: both files present, deep-merge -----------------------------


def test_project_overrides_user_at_leaf(home_dir: Path, project_dir: Path) -> None:
    _write_user_config(home_dir, '[triggers]\nafter_agent = "off"\n')
    _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.triggers_after_agent == "on"


def test_user_only_table_preserved_in_extras(
    home_dir: Path, project_dir: Path
) -> None:
    _write_user_config(home_dir, '[logging]\nlevel = "debug"\n')
    _write_project_config(project_dir, '[worker]\nmode = "on"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.extras["logging"]["level"] == "debug"
    assert cfg.worker_mode == "on"


def test_project_only_table_preserved_in_extras(
    home_dir: Path, project_dir: Path
) -> None:
    _write_user_config(home_dir, '[triggers]\nafter_agent = "on"\n')
    _write_project_config(project_dir, '[telemetry]\nendpoint = "https://x"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.triggers_after_agent == "on"
    assert cfg.extras["telemetry"]["endpoint"] == "https://x"


# ---- Req 3.4: only user file exists --------------------------------------


def test_only_user_file_recognized_keys_and_defaults(
    home_dir: Path, project_dir: Path
) -> None:
    _write_user_config(
        home_dir,
        '[triggers]\nscheduler = "on"\n[distill]\nmode = "inline"\n',
    )
    cfg = load_merged_config(str(project_dir))
    assert cfg.triggers_scheduler == "on"
    assert cfg.distill_mode == "inline"
    assert cfg.triggers_after_agent == "off"
    assert cfg.worker_mode == "off"


# ---- Req 3.5: neither file exists ----------------------------------------


def test_neither_file_returns_all_defaults(
    home_dir: Path, project_dir: Path
) -> None:
    cfg = load_merged_config(str(project_dir))
    assert cfg == MergedConfig()


# ---- Req 3.6: each recognized key's allowed values accepted --------------


@pytest.mark.parametrize("value", ["off", "on"])
def test_triggers_after_agent_allowed_values(
    home_dir: Path, project_dir: Path, value: str
) -> None:
    _write_project_config(project_dir, f'[triggers]\nafter_agent = "{value}"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.triggers_after_agent == value


@pytest.mark.parametrize("value", ["defer_to_agent", "inline", "worker"])
def test_distill_mode_allowed_values(
    home_dir: Path, project_dir: Path, value: str
) -> None:
    _write_project_config(project_dir, f'[distill]\nmode = "{value}"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.distill_mode == value


def test_defaults_are_correct() -> None:
    cfg = MergedConfig()
    assert cfg.triggers_after_agent == "off"
    assert cfg.triggers_scheduler == "off"
    assert cfg.distill_mode == "defer_to_agent"
    assert cfg.worker_mode == "off"
    assert cfg.autopilot_enabled is True
    assert cfg.dream_auto_enabled is False
    assert cfg.dream_parse_parse_all is True
    assert cfg.dream_handle_handle_all is True
    assert cfg.dream_handle_allow_delete_truth is False
    assert cfg.dream_handle_preserve_audit is True
    assert cfg.extras == {}


def test_dream_config_project_values_load_and_round_trip(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(
        project_dir,
        "[dream.auto]\n"
        "enabled = true\n"
        'trigger = "idle"\n'
        "min_interval_hours = 2\n"
        "idle_seconds = 30\n"
        "max_runtime_seconds = 45\n"
        "[dream.parse]\n"
        "parse_all = true\n"
        "require_evidence = false\n"
        "[dream.handle]\n"
        "handle_all = true\n"
        "allow_mark_stale = false\n"
        "allow_delete_truth = false\n"
        "preserve_audit = true\n"
        "undo_window_days = 7\n",
    )

    cfg = load_merged_config(str(project_dir))

    assert cfg.dream_auto_enabled is True
    assert cfg.dream_auto_trigger == "idle"
    assert cfg.dream_auto_min_interval_hours == 2
    assert cfg.dream_auto_idle_seconds == 30
    assert cfg.dream_auto_max_runtime_seconds == 45
    assert cfg.dream_parse_require_evidence is False
    assert cfg.dream_handle_allow_mark_stale is False
    assert cfg.dream_handle_undo_window_days == 7
    rc = cfg.to_reflection_config()
    assert rc["dream"]["auto"]["enabled"] is True
    assert rc["dream"]["parse"]["parse_all"] is True
    assert rc["dream"]["handle"]["allow_delete_truth"] is False


def test_autopilot_config_project_values_load_and_round_trip(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(
        project_dir,
        "[autopilot]\n"
        "enabled = false\n",
    )

    cfg = load_merged_config(str(project_dir))

    assert cfg.autopilot_enabled is False
    rc = cfg.to_reflection_config()
    assert rc["autopilot"]["enabled"] is False


@pytest.mark.parametrize(
    "body,key_path",
    [
        ('[autopilot]\nwrite_candidates = "ask"\n', "autopilot.write_candidates"),
        ("[autopilot]\nauto_wake = true\n", "autopilot.auto_wake"),
        ("[autopilot]\nauto_search = true\n", "autopilot.auto_search"),
        (
            "[autopilot]\nsuggest_on_stable_result = true\n",
            "autopilot.suggest_on_stable_result",
        ),
        (
            "[autopilot]\nauto_confirm_low_risk = true\n",
            "autopilot.auto_confirm_low_risk",
        ),
        ('[autopilot]\nenabled = "yes"\n', "autopilot.enabled"),
    ],
)
def test_autopilot_config_rejects_invalid_values(
    home_dir: Path,
    project_dir: Path,
    body: str,
    key_path: str,
) -> None:
    proj_path = _write_project_config(project_dir, body)

    with pytest.raises(ConfigValidationError) as excinfo:
        load_merged_config(str(project_dir))

    assert excinfo.value.key_path == key_path
    assert excinfo.value.source_path == str(proj_path)


@pytest.mark.parametrize(
    "body,key_path",
    [
        ("[dream.parse]\nparse_all = false\n", "dream.parse.parse_all"),
        ("[dream.handle]\nhandle_all = false\n", "dream.handle.handle_all"),
        (
            "[dream.handle]\nallow_delete_truth = true\n",
            "dream.handle.allow_delete_truth",
        ),
        (
            "[dream.handle]\npreserve_audit = false\n",
            "dream.handle.preserve_audit",
        ),
        (
            "[dream.auto]\nmin_interval_hours = 0\n",
            "dream.auto.min_interval_hours",
        ),
    ],
)
def test_dream_config_rejects_values_that_break_v31_contract(
    home_dir: Path,
    project_dir: Path,
    body: str,
    key_path: str,
) -> None:
    proj_path = _write_project_config(project_dir, body)

    with pytest.raises(ConfigValidationError) as excinfo:
        load_merged_config(str(project_dir))

    assert excinfo.value.key_path == key_path
    assert excinfo.value.source_path == str(proj_path)


# ---- Req 3.7: invalid recognized value -----------------------------------


def test_invalid_value_in_project_file_raises_with_attribution(
    home_dir: Path, project_dir: Path
) -> None:
    proj_path = _write_project_config(
        project_dir, '[triggers]\nafter_agent = "sometimes"\n'
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        load_merged_config(str(project_dir))
    err = excinfo.value
    assert err.key_path == "triggers.after_agent"
    assert err.value == "sometimes"
    assert err.source_path == str(proj_path)


def test_invalid_value_in_user_file_raises_with_attribution(
    home_dir: Path, project_dir: Path
) -> None:
    user_path = _write_user_config(home_dir, '[worker]\nmode = "daemon"\n')
    with pytest.raises(ConfigValidationError) as excinfo:
        load_merged_config(str(project_dir))
    err = excinfo.value
    assert err.key_path == "worker.mode"
    assert err.value == "daemon"
    assert err.source_path == str(user_path)


def test_project_invalid_value_attributed_to_project_not_user(
    home_dir: Path, project_dir: Path
) -> None:
    _write_user_config(home_dir, '[distill]\nmode = "inline"\n')
    proj_path = _write_project_config(
        project_dir, '[distill]\nmode = "nonsense"\n'
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        load_merged_config(str(project_dir))
    assert excinfo.value.source_path == str(proj_path)


# ---- Req 3.8: malformed TOML ---------------------------------------------


def test_malformed_project_toml_raises_parse_error(
    home_dir: Path, project_dir: Path
) -> None:
    proj_path = _write_project_config(project_dir, "this is = = not valid toml\n")
    with pytest.raises(ConfigParseError) as excinfo:
        load_merged_config(str(project_dir))
    assert excinfo.value.source_path == str(proj_path)


def test_malformed_user_toml_raises_parse_error(
    home_dir: Path, project_dir: Path
) -> None:
    user_path = _write_user_config(home_dir, "broken [[[ toml\n")
    with pytest.raises(ConfigParseError) as excinfo:
        load_merged_config(str(project_dir))
    assert excinfo.value.source_path == str(user_path)


# ---- Req 3.9: to_reflection_config nested shape --------------------------


def test_to_reflection_config_nested_shape(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(
        project_dir,
        '[triggers]\nafter_agent = "on"\nscheduler = "on"\n'
        '[distill]\nmode = "worker"\n[worker]\nmode = "on"\n',
    )
    cfg = load_merged_config(str(project_dir))
    rc = cfg.to_reflection_config()
    assert rc.get("distill", {}).get("mode") == "worker"
    assert rc["triggers"]["after_agent"] == "on"
    assert rc["triggers"]["scheduler"] == "on"
    assert rc["worker"]["mode"] == "on"


def test_to_reflection_config_preserves_unknown_extras(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(
        project_dir,
        '[logging]\nlevel = "debug"\n[distill]\nmode = "inline"\n',
    )
    cfg = load_merged_config(str(project_dir))
    rc = cfg.to_reflection_config()
    assert rc["logging"]["level"] == "debug"
    assert rc["distill"]["mode"] == "inline"


def test_to_reflection_config_recognized_overrides_extras_at_same_path(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(
        project_dir,
        '[triggers]\nafter_agent = "on"\ncustom_thing = "keep-me"\n',
    )
    cfg = load_merged_config(str(project_dir))
    assert "after_agent" not in cfg.extras.get("triggers", {})
    assert cfg.extras["triggers"]["custom_thing"] == "keep-me"
    rc = cfg.to_reflection_config()
    assert rc["triggers"]["after_agent"] == "on"
    assert rc["triggers"]["custom_thing"] == "keep-me"


# ---- Req 3.10: determinism -----------------------------------------------


def test_determinism_byte_identical_files(
    home_dir: Path, project_dir: Path
) -> None:
    user_body = '[triggers]\nafter_agent = "off"\n[logging]\nlevel = "info"\n'
    proj_body = (
        '[triggers]\nafter_agent = "on"\n[distill]\nmode = "worker"\n'
        '[telemetry]\nendpoint = "https://x"\nbatch = 10\n'
    )
    _write_user_config(home_dir, user_body)
    _write_project_config(project_dir, proj_body)
    first = load_merged_config(str(project_dir))
    second = load_merged_config(str(project_dir))
    assert first == second


# ---- extras: unknown top-level table -------------------------------------


def test_unknown_table_lands_in_extras_and_round_trips(
    home_dir: Path, project_dir: Path
) -> None:
    _write_project_config(project_dir, '[logging]\nlevel = "debug"\n')
    cfg = load_merged_config(str(project_dir))
    assert cfg.extras["logging"]["level"] == "debug"
    rc = cfg.to_reflection_config()
    assert rc["logging"]["level"] == "debug"


# ---- frozen dataclass behavior -------------------------------------------


def test_merged_config_is_frozen() -> None:
    cfg = MergedConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.triggers_after_agent = "on"  # type: ignore[misc]


def test_merged_config_equality_field_for_field() -> None:
    a = MergedConfig(triggers_after_agent="on", extras={"x": {"y": 1}})
    b = MergedConfig(triggers_after_agent="on", extras={"x": {"y": 1}})
    assert a == b


# ---- deep_merge unit -----------------------------------------------------


def test_deep_merge_recursive_and_leaf_override() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    overlay = {"a": {"y": 3, "z": 4}, "c": 5}
    out = deep_merge(base, overlay)
    assert out == {"a": {"x": 1, "y": 3, "z": 4}, "b": 1, "c": 5}
    assert base == {"a": {"x": 1, "y": 2}, "b": 1}
