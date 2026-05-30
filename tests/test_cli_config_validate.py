"""Tests for ``cmd_config_validate`` (v2.4.3 Task 2, Req 4; covers Property 3).

HOME isolation
--------------
``cmd_config_validate`` resolves the user-level config path through
``load_merged_config`` -> ``Path.home()``. Tests redirect that lookup to a tmp
directory by monkeypatching ``Path.home`` so no test reads the real
``~/.harness-mem/config.toml`` (project rule P1: data-path isolation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import cmd_config_validate
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import load_merged_config


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


# ---- Req 4.2: success path ------------------------------------------------


def test_validate_success(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    rc = cmd_config_validate(str(project_dir))
    assert rc == 0
    out = capsys.readouterr()
    assert out.out.strip() == f"config valid: {project_dir}"
    assert out.err == ""


def test_validate_success_when_no_files(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_validate(str(project_dir))
    assert rc == 0
    assert capsys.readouterr().out.strip() == f"config valid: {project_dir}"


# ---- Req 4.3: parse error path -------------------------------------------


def test_validate_parse_error(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj_path = _write_project_config(project_dir, "this is = = not valid toml\n")
    rc = cmd_config_validate(str(project_dir))
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.startswith("parse error: ")
    assert str(proj_path) in out.err


# ---- Req 4.4: schema error path ------------------------------------------


def test_validate_schema_error(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj_path = _write_project_config(project_dir, '[triggers]\nafter_agent = "maybe"\n')
    rc = cmd_config_validate(str(project_dir))
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "invalid value: triggers.after_agent = maybe" in out.err
    assert str(proj_path) in out.err


def test_validate_schema_error_in_user_file(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    user_path = _write_user_config(home_dir, '[worker]\nmode = "daemon"\n')
    rc = cmd_config_validate(str(project_dir))
    assert rc == 1
    out = capsys.readouterr()
    assert "invalid value: worker.mode = daemon" in out.err
    assert str(user_path) in out.err


# ---- Req 4.5: project-root override --------------------------------------


def test_project_root_defaults_to_cwd(
    home_dir: Path,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_project_config(project_dir, '[distill]\nmode = "inline"\n')
    monkeypatch.chdir(project_dir)
    rc = cmd_config_validate(None)
    assert rc == 0
    assert capsys.readouterr().out.strip().endswith("config valid: " + str(project_dir))


# ---- Req 4.6: read-only ---------------------------------------------------


def test_validate_is_read_only(home_dir: Path, project_dir: Path) -> None:
    proj_path = _write_project_config(project_dir, '[triggers]\nafter_agent = "on"\n')
    before = proj_path.read_text(encoding="utf-8")
    cmd_config_validate(str(project_dir))
    assert proj_path.read_text(encoding="utf-8") == before


# ---- Req 4.7 / Property 3: single source of truth ------------------------


@pytest.mark.parametrize(
    "body",
    [
        '[triggers]\nafter_agent = "on"\n',  # valid
        '[triggers]\nafter_agent = "maybe"\n',  # schema error
        "this is = = not valid toml\n",  # parse error
        '[distill]\nmode = "worker"\n[worker]\nmode = "on"\n',  # valid
    ],
)
def test_validate_outcome_matches_loader(
    home_dir: Path, project_dir: Path, body: str
) -> None:
    _write_project_config(project_dir, body)

    # In-process loader outcome.
    try:
        load_merged_config(str(project_dir))
        loader_ok = True
    except ConfigError:
        loader_ok = False

    # CLI handler outcome.
    rc = cmd_config_validate(str(project_dir))
    cli_ok = rc == 0

    assert cli_ok == loader_ok
