"""Tests for ``cmd_config_list`` (v2.4.3 Task 2, Req 3).

HOME isolation
--------------
``cmd_config_list`` resolves the user-level config path through
``load_merged_config`` -> ``Path.home()``. Tests redirect that lookup to a tmp
directory by monkeypatching ``Path.home`` so no test reads the real
``~/.harness-mem/config.toml`` (project rule P1: data-path isolation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import cmd_config_list


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


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


# ---- Req 3.6: both files absent -> header note + all defaults ------------


def test_both_absent_prints_header_note_and_defaults(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_list(str(project_dir))
    assert rc == 0
    out = capsys.readouterr()
    assert out.err == ""
    lines = _lines(out.out)
    assert lines[0] == "no Config_File found, showing defaults"
    body = "\n".join(lines[1:])
    assert "triggers.after_agent = off  (default)" in body
    assert "triggers.scheduler = off  (default)" in body
    assert "distill.mode = defer_to_agent  (default)" in body
    assert "worker.mode = off  (default)" in body
    assert "autopilot.enabled = true  (default)" in body


# ---- Req 3.2: source labels for default / user / project -----------------


def test_source_labels_project_user_default(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_user_config(home_dir, '[triggers]\nscheduler = "on"\n')
    _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')

    rc = cmd_config_list(str(project_dir))
    assert rc == 0
    out = capsys.readouterr().out
    # project file supplies after_agent
    assert "triggers.after_agent = on  (project)" in out
    # user file supplies scheduler
    assert "triggers.scheduler = on  (user)" in out
    # neither file supplies distill.mode / worker.mode -> default
    assert "distill.mode = defer_to_agent  (default)" in out
    assert "worker.mode = off  (default)" in out
    # no header note when at least one file is present
    assert "no Config_File found" not in out


def test_project_overrides_user_label_is_project(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_user_config(home_dir, '[triggers]\nafter_agent = "off"\n')
    _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    cmd_config_list(str(project_dir))
    out = capsys.readouterr().out
    assert "triggers.after_agent = on  (project)" in out


# ---- Req 3.3: extras (non-recognized keys) printed with source -----------


def test_extras_printed_with_source(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_user_config(home_dir, '[logging]\nlevel = "debug"\n')
    _write_project_config(project_dir, '[telemetry]\nendpoint = "https://x"\n')
    cmd_config_list(str(project_dir))
    out = capsys.readouterr().out
    assert "logging.level = debug  (user)" in out
    assert "telemetry.endpoint = https://x  (project)" in out


# ---- Req 3.4: project-root override --------------------------------------


def test_project_root_defaults_to_cwd(
    home_dir: Path,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_project_config(project_dir, '[worker]\nmode = "on"\n')
    monkeypatch.chdir(project_dir)
    rc = cmd_config_list(None)
    assert rc == 0
    assert "worker.mode = on  (project)" in capsys.readouterr().out


# ---- Req 3.5: read-only — no mutation ------------------------------------


def test_list_is_read_only(home_dir: Path, project_dir: Path) -> None:
    proj_path = _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    user_path = _write_user_config(home_dir, '[worker]\nmode = "on"\n')
    proj_before = proj_path.read_text(encoding="utf-8")
    user_before = user_path.read_text(encoding="utf-8")

    cmd_config_list(str(project_dir))

    assert proj_path.read_text(encoding="utf-8") == proj_before
    assert user_path.read_text(encoding="utf-8") == user_before


def test_list_both_absent_creates_no_files(
    home_dir: Path, project_dir: Path
) -> None:
    cmd_config_list(str(project_dir))
    assert not (project_dir / ".harness-mem.toml").exists()
    assert not (home_dir / ".harness-mem" / "config.toml").exists()
