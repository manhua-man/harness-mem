"""Tests for ``cmd_config_set`` (v2.4.3 Task 2, Req 2; covers Property 1).

HOME isolation
--------------
``cmd_config_set`` resolves the user-level config path through
``set_value`` -> ``Path.home()``. Tests redirect that lookup to a tmp directory
by monkeypatching ``Path.home`` so no test writes the real
``~/.harness-mem/config.toml`` (project rule P1: data-path isolation).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from harness_mem.commands.config_cmds import cmd_config_get, cmd_config_set
from harness_mem.config.merge import _RECOGNIZED_KEYS


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` to an isolated tmp dir for user-config writes."""
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


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---- Property 1: round-trip set -> get returns the value -----------------


@pytest.mark.parametrize(
    ("key_path", "value"),
    [
        (key_path, value)
        for key_path, _attr, allowed, _default in _RECOGNIZED_KEYS
        for value in allowed
    ],
)
@pytest.mark.parametrize("scope", ["user", "project"])
def test_round_trip_set_then_get(
    home_dir: Path,
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    scope: str,
    key_path: str,
    value: str,
) -> None:
    rc_set = cmd_config_set(key_path, value, scope, str(project_dir))
    assert rc_set == 0
    capsys.readouterr()  # drain the "wrote ..." line

    rc_get = cmd_config_get(key_path, str(project_dir))
    assert rc_get == 0
    assert capsys.readouterr().out.strip() == value


# ---- Req 2.7: success prints confirmation to stdout, exit 0 --------------


def test_set_success_confirmation_shape(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_set("triggers.after_agent", "on", "project", str(project_dir))
    assert rc == 0
    out = capsys.readouterr()
    target = (project_dir / ".harness-mem.toml").resolve()
    assert out.out.strip() == f"wrote {target}: triggers.after_agent = on"
    assert out.err == ""


def test_set_dream_auto_enabled_round_trips_through_get(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc_set = cmd_config_set(
        "dream.auto.enabled",
        "true",
        "project",
        str(project_dir),
    )
    assert rc_set == 0
    capsys.readouterr()

    rc_get = cmd_config_get("dream.auto.enabled", str(project_dir))

    assert rc_get == 0
    assert capsys.readouterr().out.strip() == "true"


def test_set_unknown_autopilot_key_is_rejected(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_set(
        "autopilot.write_candidates",
        "on",
        "project",
        str(project_dir),
    )

    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "invalid value: autopilot.write_candidates = on" in out.err
    assert "allowed: {}" in out.err
    assert not (project_dir / ".harness-mem.toml").exists()


# ---- Req 2.5: allowed-value validation rejection -------------------------


def test_invalid_recognized_value_rejected(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_config_set(
        "triggers.after_agent", "sometimes", "project", str(project_dir)
    )
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "invalid value: triggers.after_agent = sometimes" in out.err
    assert "allowed: {off, on}" in out.err
    # Req 2.5: the file must not be created when validation fails.
    assert not (project_dir / ".harness-mem.toml").exists()


@pytest.mark.parametrize(
    ("key_path", "value", "allowed"),
    [
        ("dream.parse.parse_all", "false", "{true}"),
        ("dream.handle.handle_all", "false", "{true}"),
        ("dream.handle.allow_delete_truth", "true", "{false}"),
        ("dream.handle.preserve_audit", "false", "{true}"),
    ],
)
def test_invalid_dream_contract_value_rejected(
    home_dir: Path,
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    key_path: str,
    value: str,
    allowed: str,
) -> None:
    rc = cmd_config_set(key_path, value, "project", str(project_dir))

    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert f"invalid value: {key_path} = {value}" in out.err
    assert f"allowed: {allowed}" in out.err
    assert not (project_dir / ".harness-mem.toml").exists()


# ---- Req 2.3: file + parent dir creation when absent ---------------------


def test_user_scope_creates_file_and_parent_dir(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_dir = home_dir / ".harness-mem"
    assert not cfg_dir.exists()
    rc = cmd_config_set("worker.mode", "on", "user", str(project_dir))
    assert rc == 0
    target = cfg_dir / "config.toml"
    assert target.is_file()
    assert _read_toml(target)["worker"]["mode"] == "on"


# ---- Req 2.6: preserve other keys ----------------------------------------


def test_preserves_other_keys(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project_dir / ".harness-mem.toml"
    target.write_text(
        '[logging]\nlevel = "debug"\n[triggers]\nscheduler = "on"\n',
        encoding="utf-8",
    )
    rc = cmd_config_set("triggers.after_agent", "on", "project", str(project_dir))
    assert rc == 0
    data = _read_toml(target)
    assert data["triggers"]["after_agent"] == "on"
    assert data["triggers"]["scheduler"] == "on"
    assert data["logging"]["level"] == "debug"


# ---- Req 2.2/2.3/2.4: user vs project scope write the correct path -------


def test_user_scope_writes_user_path_only(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_config_set("worker.mode", "on", "user", str(project_dir))
    assert (home_dir / ".harness-mem" / "config.toml").is_file()
    assert not (project_dir / ".harness-mem.toml").exists()


def test_project_scope_writes_project_path_only(
    home_dir: Path, project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_config_set("worker.mode", "on", "project", str(project_dir))
    assert (project_dir / ".harness-mem.toml").is_file()
    assert not (home_dir / ".harness-mem" / "config.toml").exists()


# ---- write failure surfaces as exit 1 + stderr (Req 2 error shape) -------


def test_write_failure_surfaces_oserror(
    home_dir: Path,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "harness_mem.commands.config_cmds.set_value", _boom
    )
    rc = cmd_config_set("worker.mode", "on", "project", str(project_dir))
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "write failed:" in out.err
    assert "disk full" in out.err
