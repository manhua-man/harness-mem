"""Tests for ``cmd_config_get`` (v2.4.3 Task 2, Req 1).

HOME isolation
--------------
``cmd_config_get`` resolves the user-level config path through
``load_merged_config`` -> ``Path.home()``. Tests redirect that lookup to a tmp
directory by monkeypatching ``Path.home`` so no test reads the real
``~/.harness-mem/config.toml`` (project rule P1: data-path isolation). A
``project`` directory under ``tmp_path`` stands in for the project root.

Handlers are tested directly (not via subprocess) for exit codes and output,
matching the design's "Testing Strategy" note.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import cmd_config_get


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


def _write_project_config(project: Path, body: str) -> Path:
    path = project / ".harness-mem.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _write_user_config(home: Path, body: str) -> Path:
    cfg_dir = home / ".harness-mem"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---- Req 1.2: recognized key present resolves to its value ---------------


def test_recognized_key_present_prints_value(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    rc = cmd_config_get("triggers.after_agent", str(project_dir))
    assert rc == 0
    out = capsys.readouterr()
    assert out.out.strip() == "on"
    assert out.err == ""


# ---- Req 1.3: recognized key absent falls back to declared default -------


def test_recognized_key_absent_returns_default(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_get("distill.mode", str(project_dir))
    assert rc == 0
    out = capsys.readouterr()
    assert out.out.strip() == "defer_to_agent"
    assert out.err == ""


def test_recognized_key_after_agent_default_off(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_get("triggers.after_agent", str(project_dir))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "off"


def test_recognized_key_autopilot_defaults(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_config_get("autopilot.enabled", str(project_dir)) == 0
    assert capsys.readouterr().out.strip() == "true"


# ---- extras: user-defined key present resolves --------------------------


def test_extras_key_resolves(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_config(project_dir, '[telemetry]\nendpoint = "https://x"\n')
    rc = cmd_config_get("telemetry.endpoint", str(project_dir))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "https://x"


# ---- Req 1.4: unknown key -> exit 1, stderr diagnostic, no stdout --------


def test_unknown_key_exits_1_with_stderr_and_no_stdout(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_get("nope.not_here", str(project_dir))
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.strip() == "key not found: nope.not_here"


# ---- Req 1.5: project-root override --------------------------------------


def test_project_root_override(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_config(project_dir, '[worker]\nmode = "on"\n')
    rc = cmd_config_get("worker.mode", str(project_dir))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "on"


def test_project_root_defaults_to_cwd(
    home_dir: Path,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_project_config(project_dir, '[distill]\nmode = "inline"\n')
    monkeypatch.chdir(project_dir)
    rc = cmd_config_get("distill.mode", None)
    assert rc == 0
    assert capsys.readouterr().out.strip() == "inline"


# ---- Req 1.6: read-only — no file created or modified --------------------


def test_get_is_read_only(
    home_dir: Path, project_dir: Path
) -> None:
    proj_path = _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    original = proj_path.read_text(encoding="utf-8")
    user_cfg = home_dir / ".harness-mem" / "config.toml"

    cmd_config_get("triggers.after_agent", str(project_dir))

    assert proj_path.read_text(encoding="utf-8") == original
    assert not user_cfg.exists()


def test_get_unknown_key_does_not_create_files(
    home_dir: Path, project_dir: Path
) -> None:
    proj_path = project_dir / ".harness-mem.toml"
    user_cfg = home_dir / ".harness-mem" / "config.toml"
    cmd_config_get("does.not.exist", str(project_dir))
    assert not proj_path.exists()
    assert not user_cfg.exists()
